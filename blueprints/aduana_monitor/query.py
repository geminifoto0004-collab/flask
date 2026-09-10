# -*- coding: utf-8 -*-
"""Aduana Chile Oracle APEX query engine.

Adapted from the user's proven requests.Session implementation. It keeps one
APEX session per worker for speed, refreshes hidden state after every POST,
splits ranges by natural month, deduplicates only rows whose 14 raw fields are
identical, and sorts by Emisión DESC then Notificación DESC.

A failed request/parse is retried once with a fresh APEX session. This preserves
the fast worker model while recovering from stale/invalid APEX state.
"""
from __future__ import annotations

import calendar
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import settings


class AduanaParseError(RuntimeError):
    pass


def month_chunks_for_range(start: date, end: date):
    if start > end:
        return
    cur = start
    while cur <= end:
        last_day = calendar.monthrange(cur.year, cur.month)[1]
        chunk_end = min(date(cur.year, cur.month, last_day), end)
        yield cur, chunk_end
        if chunk_end >= end:
            break
        cur = date(cur.year + (1 if cur.month == 12 else 0), 1 if cur.month == 12 else cur.month + 1, 1)


def fmt_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _find_main_form(soup: BeautifulSoup):
    target = soup.find(id="P1_FECHA_DESDE")
    if target:
        form = target.find_parent("form")
        if form:
            return form
    forms = soup.find_all("form")
    if forms:
        return max(forms, key=lambda node: len(str(node)))
    raise AduanaParseError("No se encontró el formulario principal de Aduana")


def _collect_hidden_fields(form):
    payload = []
    for tag in form.find_all("input"):
        name = tag.get("name")
        if not name:
            continue
        if (tag.get("type") or "text").lower() == "hidden":
            payload.append((name, tag.get("value", "")))
    return payload


def _remove_payload_names(payload, names):
    return [(key, value) for key, value in payload if key not in names]


class AduanaApexClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(settings.HEADERS)
        self.initialized = False
        self.payload_base = []
        self.action_url = None
        self.method = "post"
        self.referer = settings.BASE_URL

    def _update_state_from_html(self, page_url: str, page_html: str):
        soup = BeautifulSoup(page_html, "html.parser")
        form = _find_main_form(soup)
        payload = _collect_hidden_fields(form)
        self.payload_base = _remove_payload_names(
            payload, {"p_t02", "p_t03", "p_t04", "p_t05", "p_request"}
        )
        self.action_url = urljoin(page_url, form.get("action") or page_url)
        self.method = (form.get("method") or "post").lower()
        self.referer = page_url

    def initialize(self):
        if self.initialized:
            return
        response = self.session.get(
            settings.BASE_URL,
            headers=settings.HEADERS,
            timeout=settings.REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
        self._update_state_from_html(response.url, response.text)
        self.initialized = True

    def query_period(self, d1: date, d2: date, aduana: str, rut: str) -> str:
        if not self.initialized:
            self.initialize()
        payload = list(self.payload_base)
        payload.extend([
            ("p_t02", fmt_date(d1)),
            ("p_t03", fmt_date(d2)),
            ("p_t04", str(aduana)),
            ("p_t05", rut.strip()),
            ("p_request", "Go"),
        ])
        headers = dict(settings.HEADERS)
        headers["Referer"] = self.referer
        if self.method == "get":
            response = self.session.get(
                self.action_url, params=payload, headers=headers,
                timeout=settings.REQUEST_TIMEOUT, allow_redirects=True,
            )
        else:
            response = self.session.post(
                self.action_url, data=payload, headers=headers,
                timeout=settings.REQUEST_TIMEOUT, allow_redirects=True,
            )
        response.raise_for_status()
        try:
            self._update_state_from_html(response.url, response.text)
        except Exception:
            # Some valid result pages do not preserve the full search form.
            # Keep the existing state; a later failure will retry with a fresh
            # session instead of treating this as a failed query immediately.
            self.referer = response.url
        return response.text


def _looks_like_explicit_no_data(soup: BeautifulSoup) -> bool:
    text = " ".join(soup.stripped_strings).lower()
    markers = (
        "no data found",
        "no se encontraron datos",
        "no se encontraron registros",
        "no existen registros",
        "sin resultados",
        "sin datos",
        "no hay datos",
        "no se encontraron",
    )
    return any(marker in text for marker in markers)


def _find_result_table(soup: BeautifulSoup):
    table = soup.select_one("table.apexir_WORKSHEET_DATA")
    if table is not None:
        return table
    # Match the proven local scraper's fallback: some APEX responses keep the
    # WORKSHEET_DATA class but with additional/changed class names.
    for candidate in soup.find_all("table"):
        classes = " ".join(candidate.get("class") or [])
        if "WORKSHEET_DATA" in classes.upper():
            return candidate
    return None


def extract_rows(response_html: str):
    """Return ``(rows, parse_state)`` for one Aduana response.

    A result table is authoritative even if the POST response no longer carries
    every search-control element. Missing result markup is still treated as an
    error unless Aduana explicitly reports zero results, so a malformed HTTP-200
    page cannot complete a false monitoring baseline.
    """
    soup = BeautifulSoup(response_html or "", "html.parser")
    table = _find_result_table(soup)

    if table is None:
        if _looks_like_explicit_no_data(soup):
            return [], "ZERO"
        raise AduanaParseError(
            "No apareció la tabla de resultados ni un mensaje explícito de cero resultados"
        )

    rows = []
    trs = table.find_all("tr")
    if not trs:
        return [], "ZERO"

    for tr in trs[1:]:
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        if len(tds) != 14:
            # Ignore non-data rows (pagination/summary rows) exactly as the
            # proven scraper did; a real data row must have all 14 columns.
            continue
        values = [td.get_text(" ", strip=True) for td in tds]
        rows.append(dict(zip(settings.COLUMNS, values)))
    return rows, "OK" if rows else "ZERO"


def row_hash(row: dict) -> str:
    raw = "|".join(str(row.get(col, "") or "") for col in settings.COLUMNS)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _dedupe_full_rows(rows):
    seen = set()
    result = []
    for row in rows:
        key = tuple(str(row.get(col, "") or "") for col in settings.COLUMNS)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _parse_date_for_sort(value):
    text = str(value or "").strip()
    if not text:
        return date.min
    for fmt in ("%d/%m/%y", "%d-%m-%y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return date.min


def sort_rows(rows):
    return sorted(
        rows,
        key=lambda row: (
            _parse_date_for_sort(row.get("emision")),
            _parse_date_for_sort(row.get("notificacion")),
        ),
        reverse=True,
    )


def _worker(worker_id, periods, aduana, rut):
    client = AduanaApexClient()
    rows, logs = [], []

    for d1, d2 in periods:
        started = time.perf_counter()
        last_state = "REQUEST_FAILED"
        last_error = ""
        period_rows = None
        parse_state = None
        attempts = 0

        for attempt in (1, 2):
            attempts = attempt
            try:
                html = client.query_period(d1, d2, aduana, rut)
            except Exception as exc:
                last_state = "REQUEST_FAILED"
                last_error = str(exc)
            else:
                try:
                    period_rows, parse_state = extract_rows(html)
                    last_state = "OK"
                    last_error = ""
                    break
                except Exception as exc:
                    last_state = "PARSE_FAILED"
                    last_error = str(exc)

            if attempt == 1:
                # APEX hidden state/session can become stale. Retry this exact
                # month from a brand-new session before declaring it failed.
                client = AduanaApexClient()

        elapsed = round(time.perf_counter() - started, 2)
        if last_state == "OK":
            rows.extend(period_rows or [])
            logs.append({
                "worker": worker_id,
                "desde": fmt_date(d1),
                "hasta": fmt_date(d2),
                "estado": "OK",
                "resultado": parse_state,
                "filas": len(period_rows or []),
                "segundos": elapsed,
                "intentos": attempts,
            })
        else:
            logs.append({
                "worker": worker_id,
                "desde": fmt_date(d1),
                "hasta": fmt_date(d2),
                "estado": last_state,
                "filas": 0,
                "segundos": elapsed,
                "intentos": attempts,
                "error": last_error,
            })

    return rows, logs


def query_range(start_date: date, end_date: date, aduana: str, rut: str, max_workers=None):
    periods = list(month_chunks_for_range(start_date, end_date))
    if not periods:
        return [], [], True
    worker_count = min(max_workers or settings.PERIOD_WORKERS, len(periods))
    groups = [[] for _ in range(worker_count)]
    for index, period in enumerate(periods):
        groups[index % worker_count].append(period)

    all_rows, all_logs = [], []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_worker, idx + 1, group, aduana, rut) for idx, group in enumerate(groups)]
        for future in as_completed(futures):
            worker_rows, worker_logs = future.result()
            all_rows.extend(worker_rows)
            all_logs.extend(worker_logs)

    all_logs.sort(key=lambda item: item.get("desde", ""))
    all_ok = len(all_logs) == len(periods) and all(item.get("estado") == "OK" for item in all_logs)
    return sort_rows(_dedupe_full_rows(all_rows)), all_logs, all_ok


def query_last_n_days(days: int, aduana: str, rut: str, max_workers=None):
    end = date.today()
    start = end - timedelta(days=max(1, int(days)) - 1)
    return query_range(start, end, aduana, rut, max_workers=max_workers)


def query_years(years, aduana: str, rut: str, max_workers=None):
    today = date.today()
    all_rows, all_logs = [], []
    all_ok = True
    for year in sorted({int(y) for y in years}, reverse=True):
        if year < settings.UNLIMITED_START_YEAR or year > today.year:
            continue
        start = date(year, 1, 1)
        end = today if year == today.year else date(year, 12, 31)
        rows, logs, ok = query_range(start, end, aduana, rut, max_workers=max_workers)
        all_rows.extend(rows)
        all_logs.extend(logs)
        all_ok = all_ok and ok
    return sort_rows(_dedupe_full_rows(all_rows)), all_logs, all_ok
