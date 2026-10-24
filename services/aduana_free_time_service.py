"""Aduana manifest ETA & shipment-specific reference free-time (not carrier billing).

Aduana network I/O is performed only by the monitor background refresh.
Report and Telegram rendering read TiDB snapshots; no HTTP fetch on view.
"""
from __future__ import annotations

import html.parser
import http.cookiejar
import logging
import re
import threading
from datetime import date, datetime, timedelta
from urllib.parse import urlencode, urljoin
from urllib.request import Request, HTTPCookieProcessor, build_opener
from typing import Optional

from database import execute_sql, get_db_connection
from utils.time_utils import get_chile_time_naive

LOGGER = logging.getLogger(__name__)
ROOT = "http://comext.aduana.cl:7001/ManifestacionMaritima/"
SAFE_PORT = "902"
DEFAULT_DAYS = 14
_REFRESH_LOCK = threading.Lock()
_NEXT_ATTEMPT = datetime.min


def normalize_ship(name):
    return " ".join(str(name or "").upper().strip().split())[:140]


def normalize_container(code):
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())[:20]


def parse_eta(s):
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(s or ""))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def calculate(eta, days=DEFAULT_DAYS, at=None, entrega=None):
    """Reference dates only: ETA + effective days; never call this actual demurrage."""
    start = parse_eta(eta)
    if start is None:
        return None
    days = DEFAULT_DAYS if days is None else int(days)
    if not 1 <= days <= 120:
        return None
    today = at or get_chile_time_naive().date()
    limit = start + timedelta(days=days)
    remaining = (limit - today).days
    delivery = parse_eta(entrega)
    delivery_remaining = (limit - delivery).days if delivery is not None else None
    return {
        "deadline": limit.strftime("%d/%m/%Y"),
        "remaining": remaining,
        "delivery_remaining": delivery_remaining,
        "warning": remaining <= 3,
        "delivery_warning": delivery_remaining is not None and delivery_remaining <= 3,
        "days": days,
        "is_custom": days != DEFAULT_DAYS,
    }


class _Table(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in ("th", "td") and self.row is not None:
            self.cell = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self.cell is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        if tag == "tr":
            if self.row:
                self.rows.append(self.row)
            self.row = None


def fetch_month(year, month):
    """Exactly one low-frequency read-only manifest filter request for Iquique."""
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
    with opener.open(Request(ROOT, headers=headers), timeout=12) as resp:
        raw = resp.read(200000)
        first = raw.decode(resp.headers.get_content_charset() or "iso-8859-1", "replace")
    matches = re.findall(r'<form\b[^>]*\baction\s*=\s*["\']([^"\']+)["\']', first, flags=re.I)
    actions = [a for a in matches if
               a.startswith("/ManifestacionMaritima/limpiarListaProgramacionNaves.do")
               and "Naves2" not in a]
    if len(actions) != 1:
        raise RuntimeError("Aduana form not recognized; no records updated")
    action = urljoin(ROOT, actions[0].replace("&amp;", "&"))
    payload = {
        "wlw-select_key:{actionForm.puerto}OldValue": "0",
        "wlw-select_key:{actionForm.puerto}": SAFE_PORT,
        "{actionForm.anho}": str(year),
        "wlw-select_key:{actionForm.mes}OldValue": str(month),
        "wlw-select_key:{actionForm.mes}": str(month),
        "wlw-select_key:{actionForm.tipo}OldValue": "I",
        "wlw-select_key:{actionForm.tipo}": "I",
    }
    post = Request(action, data=urlencode(payload).encode(), method="POST",
                   headers={**headers, "Referer": ROOT,
                            "Content-Type": "application/x-www-form-urlencoded"})
    with opener.open(post, timeout=15) as response:
        body = response.read(1000000)
        page = body.decode(response.headers.get_content_charset() or "iso-8859-1", "replace")
    parser = _Table()
    parser.feed(page)
    found = []
    for row in parser.rows:
        if len(row) < 10 or not row[0].isdigit() or row[1].strip().upper() != "IQUIQUE":
            continue
        # Required validated columns: programación, puerto, nave, viaje,
        # agente, ETA, fecha registro, ATA, ...
        eta = parse_eta(row[5])
        if eta is None or not row[2].strip():
            continue
        found.append({
            "programacion": row[0],
            "ship_key": normalize_ship(row[2]),
            "ship_name": row[2][:140],
            "voyage": row[3][:40],
            "eta": eta,
            "ata": row[7][:40],
        })
    if not found:
        raise RuntimeError("Aduana returned no Iquique import records; retaining prior cache")
    return found


def _month_neighbors(day):
    first = day.replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    following = (first + timedelta(days=35)).replace(day=1)
    return [(d.year, d.month) for d in (prev, first, following)]


def _create_tables(conn):
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS monitor_aduana_eta (
        programacion VARCHAR(30) NOT NULL PRIMARY KEY,
        ship_key VARCHAR(140) NOT NULL,
        ship_name VARCHAR(140) NOT NULL,
        voyage VARCHAR(40) NOT NULL DEFAULT '',
        eta DATE NOT NULL,
        ata VARCHAR(40) NOT NULL DEFAULT '',
        checked_at DATETIME NOT NULL,
        INDEX idx_ship_key (ship_key, eta)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS monitor_container_free_time (
        task_id BIGINT NOT NULL,
        container_no VARCHAR(20) NOT NULL,
        programacion VARCHAR(30) NOT NULL,
        loading_date DATE NULL,
        free_days SMALLINT NULL,
        modified_at DATETIME NOT NULL,
        PRIMARY KEY (task_id, container_no, programacion)
    )""")
    conn.commit()


def refresh_aduana(names):
    """Only call from worker or admin cron; never from a page view."""
    wanted = {normalize_ship(s) for s in names if normalize_ship(s) not in ("", "UNKNOWN", "-")}
    if not wanted:
        return {"total": 0, "matched": 0}
    now = get_chile_time_naive()
    records = []
    failures = []
    # Preserve successful months even if one upstream month fails.
    for year, month in _month_neighbors(now.date()):
        try:
            records.extend(fetch_month(year, month))
        except Exception as exc:
            failures.append("%04d-%02d:%s" % (year, month, type(exc).__name__))
    if not records:
        raise RuntimeError("Aduana unavailable: " + ", ".join(failures))
    relevant = [r for r in records if r["ship_key"] in wanted
                and abs((r["eta"] - now.date()).days) <= 45]
    conn = get_db_connection()
    try:
        _create_tables(conn)
        cur = conn.cursor()
        for row in relevant:
            execute_sql(cur, """INSERT INTO monitor_aduana_eta
                (programacion,ship_key,ship_name,voyage,eta,ata,checked_at)
                VALUES (?,?,?,?,?,?,?)
                ON DUPLICATE KEY UPDATE
                ship_key=VALUES(ship_key),ship_name=VALUES(ship_name),
                voyage=VALUES(voyage),eta=VALUES(eta),ata=VALUES(ata),
                checked_at=VALUES(checked_at)""",
                (row["programacion"], row["ship_key"], row["ship_name"],
                 row["voyage"], row["eta"], row["ata"], now))
        conn.commit()
        return {"total": len(records), "matched": len(relevant), "errors": failures}
    finally:
        conn.close()


def schedule_refresh(containers):
    """At most one daemon request per process every 23h; failures retry after 1h."""
    global _NEXT_ATTEMPT
    ships = {normalize_ship(c.get("vessel_name") if c.get("matched")
                            else c.get("glosa_descripcion")) for c in containers}
    ships.discard("")
    ships.discard("UNKNOWN")
    now = get_chile_time_naive()
    if not ships or not _REFRESH_LOCK.acquire(blocking=False):
        return False
    if now < _NEXT_ATTEMPT:
        _REFRESH_LOCK.release()
        return False
    _NEXT_ATTEMPT = now + timedelta(hours=1)

    def work():
        global _NEXT_ATTEMPT
        try:
            outcome = refresh_aduana(ships)
            LOGGER.info("Aduana refresh: %s", outcome)
            _NEXT_ATTEMPT = get_chile_time_naive() + timedelta(hours=23)
        except Exception:
            LOGGER.exception("Aduana refresh failed; monitor continues using previous snapshot")
        finally:
            _REFRESH_LOCK.release()
    threading.Thread(target=work, daemon=True, name="aduana-free-time-refresh").start()
    return True


def read_enrichment(task_id, ship_names, container_names):
    """Single pair of DB reads, no network; on unavailable tables fail open."""
    ship_keys = {normalize_ship(s) for s in ship_names if normalize_ship(s)}
    codes = {normalize_container(c) for c in container_names if normalize_container(c)}
    if not ship_keys:
        return {}, {}
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        names = sorted(ship_keys)
        execute_sql(cur, """SELECT programacion,ship_key,ship_name,voyage,eta,ata,checked_at
            FROM monitor_aduana_eta WHERE ship_key IN (%s)""" % ",".join("?" for _ in names), names)
        raw = [dict(row) for row in cur.fetchall()]
        now = get_chile_time_naive()
        vessels = {}
        for key in names:
            matching = [r for r in raw if r["ship_key"] == key and
                        abs((parse_eta(r["eta"]) - now.date()).days) <= 40]
            # Same ship with multiple voyages = ambiguous. Refuse guessing.
            by_prog = {r["programacion"]: r for r in matching}
            if len(by_prog) == 1:
                candidate = next(iter(by_prog.values()))
                # Prevent showing arbitrarily stale cached ETAs.
                checked = candidate["checked_at"]
                if isinstance(checked, str):
                    checked = datetime.fromisoformat(checked)
                if checked and now - checked < timedelta(days=3):
                    vessels[key] = candidate
        overrides = {}
        if task_id and codes and vessels:
            execute_sql(cur, """SELECT task_id,container_no,programacion,loading_date,free_days
                FROM monitor_container_free_time WHERE task_id=? AND
                container_no IN (%s)""" % ",".join("?" for _ in codes),
                [int(task_id)] + sorted(codes))
            for row in cur.fetchall():
                row = dict(row)
                overrides[(normalize_container(row["container_no"]),
                           str(row["programacion"]))] = row
        return vessels, overrides
    except Exception as exc:
        LOGGER.warning("Aduana snapshot read unavailable (monitor still works): %s", type(exc).__name__)
        return {}, {}
    finally:
        if conn:
            conn.close()


def enrich_groups(matched_groups, unmatched_groups, task_id=None, today=None):
    all_groups = list(matched_groups) + list(unmatched_groups)
    vessels, overrides = read_enrichment(task_id,
        [g["nave"] for g in all_groups],
        [c["contenedor"] for g in all_groups for c in g["contenedores"]])
    today = today or get_chile_time_naive().date()
    for group in all_groups:
        rec = vessels.get(normalize_ship(group["nave"]))
        group["eta"] = parse_eta(rec["eta"]).strftime("%d/%m/%Y") if rec else None
        group["arrival_programacion"] = rec["programacion"] if rec else None
        ship_calc = calculate(rec["eta"], at=today) if rec else None
        group["ship_timer"] = ship_calc
        for c in group["contenedores"]:
            item = (overrides.get((normalize_container(c["contenedor"]), str(rec["programacion"])))
                    if rec else None)
            manual = item.get("free_days") if item else None
            # If manually specified 14d, show 14d: this is an explicit choice.
            c["manual_days"] = int(manual) if manual is not None else None
            calc = calculate(rec["eta"], manual, at=today,
                             entrega=c.get("fecha_entrega") if "fecha_entrega" in c else None) if rec else None
            c["timer"] = calc
            # The delivery-risk warning uses the ENTREGA date, not today's remaining days.
            c["delivery_risk"] = (calc["delivery_remaining"] if calc and
                                  calc["delivery_warning"] and "fecha_entrega" in c else None)
    return all_groups


def save_manual_override(task_id, container_no, free_days=None, loading_date=None):
    """Admin-only caller; bind to current unambiguous Aduana programación."""
    from services.monitor_service import get_monitor_task, _prepare_telegram_row
    task = get_monitor_task(int(task_id))
    if not task:
        raise ValueError("Monitor task not found")
    import json
    src = task.get("last_check_result") or {}
    if isinstance(src, str):
        src = json.loads(src)
    code = normalize_container(container_no)
    if not re.fullmatch(r"[A-Z]{4}\d{7}", code):
        raise ValueError("Invalid container number")
    matched = [_prepare_telegram_row(c) for c in src.get("containers", [])
               if normalize_container(c.get("glosa_codigo") or c.get("codigo")) == code]
    if len(matched) != 1:
        raise ValueError("Container is not unique in the current monitor")
    ship = matched[0]["buque"]
    vessel, _ = read_enrichment(task_id, [ship], [code])
    record = vessel.get(normalize_ship(ship))
    if not record:
        raise ValueError("Aduana voyage is missing/ambiguous; refuse to attach days to a wrong shipment")
    if free_days in (None, ""):
        days = None
    else:
        days = int(free_days)
        if not 1 <= days <= 120:
            raise ValueError("Free days must be 1..120")
    loading = None
    if loading_date:
        try:
            loading = date.fromisoformat(str(loading_date))
        except ValueError:
            raise ValueError("Loading date must be YYYY-MM-DD")
    conn = get_db_connection()
    try:
        _create_tables(conn)
        cur = conn.cursor()
        execute_sql(cur, """INSERT INTO monitor_container_free_time
            (task_id,container_no,programacion,loading_date,free_days,modified_at)
            VALUES (?,?,?,?,?,?)
            ON DUPLICATE KEY UPDATE loading_date=VALUES(loading_date),
            free_days=VALUES(free_days),modified_at=VALUES(modified_at)""",
            (int(task_id), code, str(record["programacion"]),
             loading, days, get_chile_time_naive()))
        conn.commit()
        return {"container_no": code, "programacion": str(record["programacion"]),
                "free_days": days if days is not None else DEFAULT_DAYS,
                "manual": days is not None}
    finally:
        conn.close()
