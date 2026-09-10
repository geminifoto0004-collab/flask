# -*- coding: utf-8 -*-
"""Aduana Chile Oracle APEX query engine.

The request path intentionally follows the previously proven standalone
ASYNC_4 scraper:
- each worker owns one requests.Session/APEX state;
- each worker GETs the Aduana page once, then reuses that state;
- periods are distributed round-robin across workers;
- no per-period fresh-session retry is added;
- the report parser looks for the original WORKSHEET_DATA table and ignores
  non-data rows that do not contain the expected 14 columns.

This keeps the production blueprint's dict-based output while preserving the
query behavior that was already verified against the Aduana site.
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
        cur = date(
            cur.year + (1 if cur.month == 12 else 0),
            1 if cur.month == 12 else cur.month + 1,
            1,
        )


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
    # Old APEX pages can contain duplicate hidden names, so keep list[tuple]
    # instead of converting to dict.
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
            payload,
            {"p_t02", "p_t03", "p_t04", "p_t05", "p_request"},
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
                self.action_url,
                params=payload,
                headers=headers,
                timeout=settings.REQUEST_TIMEOUT,
                allow_redirects=True,
            )
        else:
            response = self.session.post(
                self.action_url,
                data=payload,
                headers=headers,
                timeout=settings.REQUEST_TIMEOUT,
                allow_redirects=True,
            )

        response.raise_for_status()

        # Same behavior as the proven standalone scraper: try to refresh APEX
        # state, but a valid result page without a complete form must not make
        # the current query fail.
        try:
            self._update_state_from_html(response.url, response.text)
        except Exception:
            self.referer = response.url

        return response.text


def _find_result_table(soup: BeautifulSoup):
    table = soup.select_one("table.apexir_WORKSHEET_DATA")
    if table is not None:
        return table
    for candidate in soup.find_all("table"):
        classes = " ".join(candidate.get("class") or [])
        if "WORKSHEET_DATA" in classes.upper():
            return candidate
    return None


def extract_rows(response_html: str):
    """Parse the original Aduana report table.

    This deliberately mirrors the working standalone parser: absence of a
    report table is treated as an empty result for that period, and rows that
    are not the 14-column data rows are skipped.
    """
    soup = BeautifulSoup(response_html or "", "html.parser")
    table = _find_result_table(soup)
    if table is None:
        return [], "ZERO"

    rows = []
    trs = table.find_all("tr")
    if not trs:
        return [], "ZERO"

    for tr in trs[1:]:
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 14:
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
    """One independent APEX worker/session, matching ASYNC_4."""
    client = AduanaApexClient()
    rows, logs = [], []

    try:
        client.initialize()
    except Exception as exc:
        for d1, d2 in periods:
            logs.append({
                "worker": worker_id,
                "desde": fmt_date(d1),
                "hasta": fmt_date(d2),
                "estado": "REQUEST_FAILED",
                "filas": 0,
                "segundos": 0.0,
                "error": str(exc),
            })
        return rows, logs

    for d1, d2 in periods:
        started = time.perf_counter()
        try:
            html = client.query_period(d1, d2, aduana, rut)
            period_rows, parse_state = extract_rows(html)
            rows.extend(period_rows)
            logs.append({
                "worker": worker_id,
                "desde": fmt_date(d1),
                "hasta": fmt_date(d2),
                "estado": "OK",
                "resultado": parse_state,
                "filas": len(period_rows),
                "segundos": round(time.perf_counter() - started, 2),
            })
        except Exception as exc:
            logs.append({
                "worker": worker_id,
                "desde": fmt_date(d1),
                "hasta": fmt_date(d2),
                "estado": "REQUEST_FAILED",
                "filas": 0,
                "segundos": round(time.perf_counter() - started, 2),
                "error": str(exc),
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
        futures = [
            executor.submit(_worker, idx + 1, group, aduana, rut)
            for idx, group in enumerate(groups)
        ]
        for future in as_completed(futures):
            worker_rows, worker_logs = future.result()
            all_rows.extend(worker_rows)
            all_logs.extend(worker_logs)

    # Sort logs chronologically for diagnostics; data itself is sorted newest
    # first below.
    all_logs.sort(key=lambda item: item.get("desde", ""))
    all_ok = (
        len(all_logs) == len(periods)
        and all(item.get("estado") == "OK" for item in all_logs)
    )
    return sort_rows(_dedupe_full_rows(all_rows)), all_logs, all_ok


def query_last_n_days(days: int, aduana: str, rut: str, max_workers=None):
    end = date.today()
    start = end - timedelta(days=max(1, int(days)) - 1)
    return query_range(start, end, aduana, rut, max_workers=max_workers)


def query_years(years, aduana: str, rut: str, max_workers=None):
    today = date.today()
    periods = []
    for year in sorted({int(y) for y in years}, reverse=True):
        if year < settings.UNLIMITED_START_YEAR or year > today.year:
            continue
        start = date(year, 1, 1)
        end = today if year == today.year else date(year, 12, 31)
        periods.extend(month_chunks_for_range(start, end))

    if not periods:
        return [], [], True

    # Important: query all selected-year periods in one worker pool, exactly as
    # the proven ASYNC_4 implementation did, rather than creating a new pool for
    # every year.
    worker_count = min(max_workers or settings.PERIOD_WORKERS, len(periods))
    groups = [[] for _ in range(worker_count)]
    for index, period in enumerate(periods):
        groups[index % worker_count].append(period)

    all_rows, all_logs = [], []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(_worker, idx + 1, group, aduana, rut)
            for idx, group in enumerate(groups)
        ]
        for future in as_completed(futures):
            worker_rows, worker_logs = future.result()
            all_rows.extend(worker_rows)
            all_logs.extend(worker_logs)

    all_logs.sort(key=lambda item: item.get("desde", ""))
    all_ok = (
        len(all_logs) == len(periods)
        and all(item.get("estado") == "OK" for item in all_logs)
    )
    return sort_rows(_dedupe_full_rows(all_rows)), all_logs, all_ok
