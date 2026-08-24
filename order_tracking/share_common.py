"""Shared customer-share presentation helpers for local ORDER and Render.

Keep business-only presentation data here so the local guest page and the Render
public share can use the same shipping semantics.  The helpers are read-only: they
never change ORDER status/history and never touch image storage.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Mapping, MutableMapping

PARTIAL_SHIPPED = "PARTIAL_SHIPPED"
ALL_SHIPPED = "ALL_SHIPPED"
COMPLETED = "COMPLETED"

# Current + historical auto-complete notes. A COMPLETED row with one of these notes is
# only the automatic state transition after ALL_SHIPPED, not a second shipping event.
_AUTO_COMPLETE_NOTES = {
    "系統自動：已全部出貨後轉為已完成",
    "全部出货，订单自动完成",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _status(row: Mapping[str, Any]) -> str:
    return _text(row.get("status") or row.get("to_status") or row.get("current_status")).upper()


def _sort_key(row: Mapping[str, Any], position: int) -> tuple[str, str, int, int]:
    return (
        _text(row.get("action_date") or row.get("date")),
        _text(row.get("created_at")),
        int(row.get("id") or 0) if str(row.get("id") or "").isdigit() else 0,
        int(position),
    )


def derive_shipping_summary(history_rows: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Return the same shipping summary used by the main ORDER list.

    PARTIAL_SHIPPED rows are counted independently. ALL_SHIPPED is a shipping event.
    COMPLETED is also treated as a shipping event except for the automatic completion
    row generated immediately after ALL_SHIPPED.
    """
    rows = [dict(row) for row in (history_rows or []) if isinstance(row, Mapping)]
    if not rows:
        return {}

    rows = [row for _, row in sorted(enumerate(rows), key=lambda pair: _sort_key(pair[1], pair[0]))]
    partial_count = sum(1 for row in rows if _status(row) == PARTIAL_SHIPPED)
    shipping_rows = []
    for row in rows:
        status = _status(row)
        if status not in {PARTIAL_SHIPPED, ALL_SHIPPED, COMPLETED}:
            continue
        if status == COMPLETED and _text(row.get("notes")) in _AUTO_COMPLETE_NOTES:
            continue
        if not _text(row.get("action_date") or row.get("date")):
            continue
        shipping_rows.append(row)
    if not shipping_rows:
        return {}

    last = shipping_rows[-1]
    return {
        "last_shipping_date": _text(last.get("action_date") or last.get("date")),
        "last_shipping_status": _status(last),
        "partial_ship_count": partial_count,
    }


def _date_parts(value: Any) -> tuple[str, str]:
    text = _text(value)
    if not text:
        return "", ""
    date_text = text[:10]
    try:
        dt = datetime.strptime(date_text, "%Y-%m-%d")
        return f"{dt.month}/{dt.day}", f"{dt.day:02d}/{dt.month:02d}"
    except ValueError:
        return text, text


def shipping_texts(date_value: Any, status_value: Any, partial_count: Any = 0) -> dict[str, str]:
    status = _text(status_value).upper()
    if not date_value or status not in {PARTIAL_SHIPPED, ALL_SHIPPED, COMPLETED}:
        return {"zh": "", "es": ""}

    zh_date, es_date = _date_parts(date_value)
    try:
        count = int(partial_count or 0)
    except (TypeError, ValueError):
        count = 0

    if status == PARTIAL_SHIPPED:
        zh_label = "部分出貨"
        es_label = "Envío parcial"
        suffix = f" ×{count}" if count > 1 else ""
    else:
        zh_label = "已出貨"
        es_label = "Enviado"
        suffix = ""
    return {
        "zh": f"{zh_date} {zh_label}{suffix}".strip(),
        "es": f"{es_date} {es_label}{suffix}".strip(),
    }


def apply_shipping_summary(target: MutableMapping[str, Any], summary: Mapping[str, Any] | None) -> MutableMapping[str, Any]:
    summary = dict(summary or {})
    date_value = summary.get("last_shipping_date")
    status_value = summary.get("last_shipping_status")
    count = summary.get("partial_ship_count") or 0
    if not date_value or not status_value:
        target.pop("last_shipping_date", None)
        target.pop("last_shipping_status", None)
        target.pop("partial_ship_count", None)
        target.pop("shipping_zh", None)
        target.pop("shipping_es", None)
        return target

    target["last_shipping_date"] = date_value
    target["last_shipping_status"] = status_value
    target["partial_ship_count"] = int(count or 0)
    labels = shipping_texts(date_value, status_value, count)
    target["shipping_zh"] = labels["zh"]
    target["shipping_es"] = labels["es"]
    return target


def enrich_guest_orders_shipping(conn: Any, orders: list[MutableMapping[str, Any]] | None) -> list[MutableMapping[str, Any]]:
    """Attach shipping summary to local guest-card rows in ONE SQLite query."""
    orders = list(orders or [])
    workflow_numbers = []
    seen = set()
    for item in orders:
        number = _text((item or {}).get("workflow_number"))
        if number and number not in seen:
            seen.add(number)
            workflow_numbers.append(number)
    if not workflow_numbers:
        return orders

    placeholders = ",".join("?" for _ in workflow_numbers)
    cursor = conn.cursor()
    cursor.execute(
        f"""SELECT id, workflow_number, to_status, action_date, notes, created_at
            FROM workflow_status_history
            WHERE workflow_number IN ({placeholders})
            ORDER BY workflow_number, action_date ASC, created_at ASC, id ASC""",
        workflow_numbers,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cursor.fetchall():
        data = dict(row)
        grouped[_text(data.get("workflow_number"))].append(data)

    for item in orders:
        number = _text((item or {}).get("workflow_number"))
        if number:
            apply_shipping_summary(item, derive_shipping_summary(grouped.get(number)))
    return orders
