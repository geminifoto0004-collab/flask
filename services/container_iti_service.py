import json
import time
import os
import urllib3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from database import get_db_connection, get_cursor, get_row_dict
from utils.time_utils import get_chile_time_naive

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ITI_URL = "https://sistemas.iti.cl/swi/programacion-directos-diferidos.aspx"
ITI_DEBUG = os.environ.get("ITI_DEBUG") == "1"


def normalize_container(value: str) -> str:
    if value is None:
        return ""
    return str(value).replace("-", "").replace(" ", "").upper()


def _get_hidden_value(soup: BeautifulSoup, name: str) -> Optional[str]:
    tag = soup.find("input", {"name": name})
    if not tag:
        return None
    return tag.get("value")


def fetch_iti_rows() -> List[List[str]]:
    t0 = time.time()
    session = requests.Session()

    try:
        response = session.get(ITI_URL, verify=False, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        if ITI_DEBUG:
            print(f"[ITI] failed after {time.time() - t0:.2f}s")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    viewstate = _get_hidden_value(soup, "__VIEWSTATE")
    event_validation = _get_hidden_value(soup, "__EVENTVALIDATION")
    if not viewstate or not event_validation:
        return []

    post_data = {
        "__VIEWSTATE": viewstate,
        "__EVENTVALIDATION": event_validation,
    }

    try:
        post_response = session.post(ITI_URL, data=post_data, verify=False, timeout=20)
        post_response.raise_for_status()
    except requests.RequestException:
        if ITI_DEBUG:
            print(f"[ITI] failed after {time.time() - t0:.2f}s")
        return []

    post_soup = BeautifulSoup(post_response.text, "html.parser")
    tables = post_soup.find_all("table")
    if len(tables) <= 1:
        return []

    all_data = []
    row_data_map: Dict[int, List[str]] = {}

    for index, row in enumerate(tables[1].find_all("tr")):
        cells = row.find_all("td")
        row_data = [cell.get_text(strip=True) for cell in cells]
        row_data_map[index] = row_data

        buttons = row.find_all("input", {"type": "image"})
        for button in buttons:
            button_name = button.get("name")
            if not button_name:
                continue

            button_post_data = {
                "__VIEWSTATE": viewstate,
                "__EVENTVALIDATION": event_validation,
                f"{button_name}.x": "10",
                f"{button_name}.y": "10",
            }

            try:
                t_btn0 = time.time()
                button_response = session.post(
                    ITI_URL, data=button_post_data, verify=False, timeout=20
                )
            except requests.RequestException:
                continue

            if button_response.status_code != 200:
                continue

            button_soup = BeautifulSoup(button_response.text, "html.parser")
            new_tables = button_soup.find_all("table")

            for table in new_tables:
                for r in table.find_all("tr"):
                    cells = r.find_all("td")
                    new_row_data = [cell.get_text(strip=True) for cell in cells]

                    if len(new_row_data) > 2 and new_row_data[2].isdigit():
                        new_row_data[2] = new_row_data[2].zfill(6)

                    if index in row_data_map:
                        combined = [row_data_map[index][0]] + new_row_data
                        all_data.append(combined)

    if ITI_DEBUG:
        total = time.time() - t0
        print(f"[ITI] total={total:.2f}s")

    return all_data


def build_iti_index() -> Dict[str, Dict]:
    rows = fetch_iti_rows()
    idx: Dict[str, Dict] = {}

    for item in rows:
        if len(item) != 7:
            continue

        sigla = str(item[2]).strip()
        numero = str(item[3]).strip()
        digito = str(item[4]).strip()

        if numero.isdigit() and len(numero) < 6:
            numero = numero.zfill(6)

        container_no = normalize_container(sigla + numero + digito)
        if not container_no:
            continue

        idx[container_no] = {
            "vessel": item[0],
            "folio": item[1],
            "sigla": sigla,
            "numero": numero,
            "digito": digito,
            "fecha_entrega": item[5],
            "pies": item[6],
            "raw": item,
        }

    return idx


DEFAULT_CACHE_SECONDS = 300
LOCK_SECONDS = 60

_cache = {
    "ts": 0,
    "ttl": DEFAULT_CACHE_SECONDS,
    "index": None,
    "prefix": None,
    "numero": None,
}


def _get_cache_ttl_seconds() -> int:
    env_seconds = os.environ.get("CONTAINER_ITI_CACHE_SECONDS")
    if env_seconds:
        try:
            return max(30, int(env_seconds))
        except ValueError:
            pass
    env_minutes = os.environ.get("CONTAINER_ITI_CACHE_MINUTES")
    if env_minutes:
        try:
            return max(1, int(env_minutes)) * 60
        except ValueError:
            pass
    return DEFAULT_CACHE_SECONDS


def _parse_db_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _set_cache(index: Dict[str, Dict], ttl_seconds: int) -> None:
    _cache["index"] = index or {}
    _cache["prefix"] = _build_prefix_index(_cache["index"])
    _cache["numero"] = _build_numero_index(_cache["index"])
    _cache["ts"] = time.time()
    _cache["ttl"] = ttl_seconds


def _ensure_cache_row(conn) -> None:
    cursor = get_cursor(conn)
    cursor.execute("SELECT id FROM container_iti_cache WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO container_iti_cache (id, payload, updated_at, lock_until)
            VALUES (1, NULL, NULL, NULL)
            """
        )
        conn.commit()


def _read_cache_payload(conn) -> Tuple[Optional[Dict], Optional[Dict], Optional[datetime]]:
    cursor = get_cursor(conn)
    cursor.execute(
        "SELECT payload, updated_at FROM container_iti_cache WHERE id = 1"
    )
    row = cursor.fetchone()
    if not row:
        return None, None, None
    data = get_row_dict(row, cursor) or {}
    payload = data.get("payload")
    updated_at = _parse_db_dt(data.get("updated_at"))
    if not payload:
        return None, None, updated_at
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None, None, updated_at
    return parsed, parsed, updated_at


def get_iti_cache_info() -> Dict[str, Optional[object]]:
    ttl_seconds = _get_cache_ttl_seconds()
    updated_at = None
    age_seconds = None
    conn = None

    try:
        conn = get_db_connection()
        _ensure_cache_row(conn)
        _, _, updated_at = _read_cache_payload(conn)
    except Exception:
        updated_at = None
    finally:
        if conn:
            conn.close()

    if updated_at:
        age_seconds = max(
            0.0, (get_chile_time_naive() - updated_at).total_seconds()
        )

    updated_at_str = None
    if updated_at:
        updated_at_str = updated_at.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "ttl_seconds": ttl_seconds,
        "updated_at": updated_at_str,
        "age_seconds": age_seconds,
    }


def get_iti_index_cached(allow_stale: bool = True) -> Dict[str, Dict]:
    ttl_seconds = _get_cache_ttl_seconds()
    now_ts = time.time()

    if _cache["index"] is not None:
        if allow_stale or (now_ts - _cache["ts"] <= ttl_seconds):
            return _cache["index"] or {}

    conn = None
    try:
        conn = get_db_connection()
        _ensure_cache_row(conn)
        cached_index, _stale_index, _updated_at = _read_cache_payload(conn)
        if cached_index:
            _set_cache(cached_index, ttl_seconds)
            return cached_index
    except Exception:
        if conn:
            conn.close()
        conn = None
    finally:
        if conn:
            conn.close()

    return {}


def get_iti_matches_cached(container_no: str) -> List[Dict]:
    idx = get_iti_index_cached(allow_stale=True)
    if not idx:
        return []

    numero_idx = _cache.get("numero") or {}
    container_key = normalize_container(container_no)
    if not container_key:
        return []

    matches = []
    item = match_iti(idx, container_no)
    if item:
        matches.append(item)

    numero = item.get("numero") if item else None
    if numero and numero in numero_idx:
        for value in numero_idx[numero]:
            if value not in matches:
                matches.append(value)
    return matches


def _acquire_lock(conn) -> bool:
    now = get_chile_time_naive()
    lock_until = now + timedelta(seconds=LOCK_SECONDS)
    cursor = get_cursor(conn)
    _ensure_cache_row(conn)
    cursor.execute(
        """
        UPDATE container_iti_cache
        SET lock_until = ?
        WHERE id = 1 AND (lock_until IS NULL OR lock_until < ?)
        """,
        (lock_until, now),
    )
    conn.commit()
    return (cursor.rowcount or 0) > 0


def _save_cache_payload(conn, index: Dict[str, Dict]) -> None:
    payload = json.dumps(index, ensure_ascii=False)
    now = get_chile_time_naive()
    cursor = get_cursor(conn)
    _ensure_cache_row(conn)
    cursor.execute(
        """
        UPDATE container_iti_cache
        SET payload = ?, updated_at = ?, lock_until = NULL
        WHERE id = 1
        """,
        (payload, now),
    )
    conn.commit()


def _build_prefix_index(idx: Dict[str, Dict]) -> Dict[str, Dict]:
    prefix = {}
    for key, value in idx.items():
        if len(key) >= 10:
            base = key[:10]
            if base not in prefix:
                prefix[base] = value
    return prefix

def _build_numero_index(idx: Dict[str, Dict]) -> Dict[str, List[Dict]]:
    numero_index: Dict[str, List[Dict]] = {}
    for value in idx.values():
        numero = value.get("numero")
        if not numero:
            continue
        numero_index.setdefault(numero, []).append(value)
    return numero_index



def get_iti_index(force_refresh: bool = False) -> Dict[str, Dict]:
    ttl_seconds = _get_cache_ttl_seconds()
    now_ts = time.time()

    if (
        not force_refresh
        and _cache["index"] is not None
        and (now_ts - _cache["ts"] <= ttl_seconds)
    ):
        return _cache["index"] or {}

    conn = None
    stale_index: Optional[Dict[str, Dict]] = None
    try:
        conn = get_db_connection()
        _ensure_cache_row(conn)
        cached_index, stale_index, updated_at = _read_cache_payload(conn)
        if cached_index and not force_refresh:
            if updated_at:
                age = (get_chile_time_naive() - updated_at).total_seconds()
            else:
                age = ttl_seconds + 1
            if age <= ttl_seconds:
                _set_cache(cached_index, ttl_seconds)
                conn.close()
                return cached_index
    except Exception:
        if conn:
            conn.close()
        conn = None

    try:
        if conn and _acquire_lock(conn):
            index = build_iti_index()
            _save_cache_payload(conn, index)
            _set_cache(index, ttl_seconds)
            return index
    finally:
        if conn:
            conn.close()

    if stale_index is not None:
        _set_cache(stale_index, ttl_seconds)
        return stale_index

    index = build_iti_index()
    _set_cache(index, ttl_seconds)
    return index


def match_iti(index: Dict[str, Dict], container_no: str) -> Optional[Dict]:
    key = normalize_container(container_no)
    if not key:
        return None

    exact = index.get(key)
    if exact:
        return exact

    if key.isdigit() and len(key) == 6:
        numero_idx = _cache.get("numero") or {}
        matches = numero_idx.get(key) or []
        if len(matches) == 1:
            return matches[0]
        return None

    if len(key) >= 10:
        base = key[:10]
        prefix = _cache.get("prefix") or {}
        if base in prefix:
            return prefix.get(base)

        for k, v in index.items():
            if k.startswith(base):
                return v

    return None


def query_iti_by_container(container_no: str, force_refresh: bool = False) -> Optional[Dict]:
    idx = get_iti_index(force_refresh=force_refresh)
    return match_iti(idx, container_no)



def get_iti_matches(container_no: str, force_refresh: bool = False) -> List[Dict]:
    idx = get_iti_index(force_refresh=force_refresh)
    key = normalize_container(container_no)
    if not key:
        return []
    if key.isdigit() and len(key) == 6:
        numero_idx = _cache.get("numero") or {}
        return list(numero_idx.get(key) or [])
    item = match_iti(idx, container_no)
    return [item] if item else []



def get_iti_duplicate_numeros(force_refresh: bool = False) -> List[Dict]:
    idx = get_iti_index(force_refresh=force_refresh)
    numero_idx = _cache.get("numero")
    if not numero_idx:
        numero_idx = _build_numero_index(idx)
        _cache["numero"] = numero_idx

    duplicates: List[Dict] = []
    for numero, items in numero_idx.items():
        if len(items) <= 1:
            continue
        siglas = sorted({(item.get("sigla") or "") for item in items if item.get("sigla")})
        duplicates.append({
            "numero": numero,
            "count": len(items),
            "siglas": siglas,
        })

    duplicates.sort(key=lambda x: (-x["count"], x["numero"]))
    return duplicates
