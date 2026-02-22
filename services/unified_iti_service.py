"""
Unified ITI access layer.

Purpose:
- Provide one normalized ITI data model for both monitor and container flows.
- Reuse existing container_iti_service cache/lock logic by default.
- Offer a compatibility adapter for legacy row format used by monitor code.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

from services.container_iti_service import (
    get_iti_cache_info,
    get_iti_index,
    get_iti_index_cached,
    match_iti,
    normalize_container,
)


@dataclass(frozen=True)
class UnifiedITIRecord:
    container_no: str
    vessel: str
    folio: str
    sigla: str
    numero: str
    digito: str
    fecha_entrega: str
    pies: str

    @property
    def legacy_row(self) -> List[str]:
        """
        Backward-compatible 7-column row used by old monitor matching logic:
        [vessel, folio, sigla, numero, digito, fecha_entrega, pies]
        """
        return [
            self.vessel,
            self.folio,
            self.sigla,
            self.numero,
            self.digito,
            self.fecha_entrega,
            self.pies,
        ]

    @property
    def date_key(self) -> str:
        """Stable key for 'has changed' checks in cron logic."""
        return (self.fecha_entrega or "").strip()


def _normalize_index_item(container_no: str, item: Dict) -> UnifiedITIRecord:
    return UnifiedITIRecord(
        container_no=normalize_container(container_no),
        vessel=str(item.get("vessel") or "").strip(),
        folio=str(item.get("folio") or "").strip(),
        sigla=str(item.get("sigla") or "").strip(),
        numero=str(item.get("numero") or "").strip(),
        digito=str(item.get("digito") or "").strip(),
        fecha_entrega=str(item.get("fecha_entrega") or "").strip(),
        pies=str(item.get("pies") or "").strip(),
    )


def get_unified_iti_index(
    *,
    allow_stale: bool = True,
    force_refresh: bool = False,
) -> Dict[str, UnifiedITIRecord]:
    """
    Get ITI index as normalized objects.

    - force_refresh=True: pull through container_iti_service refresh path.
    - allow_stale=True: read existing cache payload when available.
    """
    if force_refresh:
        raw_index = get_iti_index(force_refresh=True)
    elif allow_stale:
        raw_index = get_iti_index_cached(allow_stale=True)
    else:
        raw_index = get_iti_index(force_refresh=False)

    normalized: Dict[str, UnifiedITIRecord] = {}
    for key, value in (raw_index or {}).items():
        record = _normalize_index_item(key, value or {})
        if not record.container_no:
            continue
        normalized[record.container_no] = record
    return normalized


def get_unified_iti_records(
    *,
    allow_stale: bool = True,
    force_refresh: bool = False,
) -> List[UnifiedITIRecord]:
    index = get_unified_iti_index(
        allow_stale=allow_stale,
        force_refresh=force_refresh,
    )
    return list(index.values())


def get_unified_iti_legacy_rows(
    *,
    allow_stale: bool = True,
    force_refresh: bool = False,
) -> List[List[str]]:
    """
    Adapter output for old code that still expects iti_data()-style rows.
    """
    return [
        record.legacy_row
        for record in get_unified_iti_records(
            allow_stale=allow_stale,
            force_refresh=force_refresh,
        )
    ]


def get_unified_iti_legacy_rows_fresh(
    *,
    max_age_seconds: int = 300,
) -> Tuple[List[List[str]], Dict[str, Optional[object]]]:
    """
    Monitor-friendly ITI accessor:
    - if cache age <= max_age_seconds: use cached data
    - else: force refresh once, then return updated cache payload
    """
    max_age_seconds = max(30, int(max_age_seconds or 300))
    info_before = get_unified_iti_cache_info()
    age = info_before.get("age_seconds")

    should_refresh = age is None
    if isinstance(age, (int, float)):
        should_refresh = age > max_age_seconds

    if should_refresh:
        rows = get_unified_iti_legacy_rows(force_refresh=True)
        info_after = get_unified_iti_cache_info()
        return rows, {
            **info_after,
            "refreshed": True,
            "max_age_seconds": max_age_seconds,
        }

    rows = get_unified_iti_legacy_rows(allow_stale=True)
    return rows, {
        **info_before,
        "refreshed": False,
        "max_age_seconds": max_age_seconds,
    }


def query_unified_iti(
    container_no: str,
    *,
    allow_stale: bool = True,
    force_refresh: bool = False,
) -> Optional[UnifiedITIRecord]:
    key = normalize_container(container_no)
    if not key:
        return None

    if force_refresh:
        raw_index = get_iti_index(force_refresh=True)
    elif allow_stale:
        raw_index = get_iti_index_cached(allow_stale=True)
    else:
        raw_index = get_iti_index(force_refresh=False)

    matched = match_iti(raw_index or {}, key)
    if not matched:
        return None
    return _normalize_index_item(key, matched)


def get_unified_iti_date_map(
    *,
    allow_stale: bool = True,
    force_refresh: bool = False,
) -> Dict[str, str]:
    """
    Minimal map used by monitor/bot cron:
    container_no -> fecha_entrega string
    """
    date_map: Dict[str, str] = {}
    for record in get_unified_iti_records(
        allow_stale=allow_stale,
        force_refresh=force_refresh,
    ):
        date_map[record.container_no] = record.date_key
    return date_map


def get_unified_iti_cache_info() -> Dict[str, Optional[object]]:
    return get_iti_cache_info()


def refresh_unified_iti_cache(*, force: bool = True) -> Dict[str, Optional[object]]:
    """
    Refresh ITI cache through shared container_iti_service pipeline.
    Returns cache metadata with item count and force flag.
    """
    index = get_unified_iti_index(force_refresh=force, allow_stale=False)
    info = get_unified_iti_cache_info()
    return {
        **info,
        "refreshed": True,
        "force": bool(force),
        "items": len(index or {}),
    }


def to_dict(record: UnifiedITIRecord) -> Dict[str, str]:
    """Helper for JSON responses/logging."""
    return asdict(record)
