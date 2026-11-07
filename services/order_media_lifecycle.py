"""Pure lifecycle policy. Physical object deletion requires an independently reviewed plan."""
from datetime import datetime
from zoneinfo import ZoneInfo

CANCELLED = {'CANCELLED', 'CANCELED', 'CANCELADO', 'CANCELADA', '已取消'}


def source_match(asset, order):
    if not order.get('image_sources_authoritative'):
        return None
    key = (str(asset.get('workflow_key') or ''), str(asset.get('sha256') or ''))
    matches = [s for s in order.get('image_sources') or []
               if (str(s.get('workflow_key') or ''), str(s.get('sha256') or '')) == key]
    return max(matches, key=lambda s: int(s.get('uploaded_at_epoch') or 0)) if matches else False


def is_bulk_photo(asset, order):
    """Per-attachment source metadata, never the order-level has_bulk_photo flag.

    Works for legacy assets too once their unchanged SHA is registered; does not
    query B2 or resurrect images filtered by source_match/customer_visible.
    """
    key = (str(asset.get('workflow_key') or ''), str(asset.get('sha256') or ''))
    return any(
        (str(source.get('workflow_key') or ''), str(source.get('sha256') or '')) == key
        and str(source.get('attachment_purpose') or '').lower() == 'bulk_photo'
        for source in (order.get('image_sources') or [])
        if isinstance(source, dict)
    )


def pending_pickup(order):
    return any(str(r.get('status') or '').upper() == 'ARRIVED_IQUIQUE'
               and str(r.get('pickup_status') or '').lower() != 'picked_up'
               for r in order.get('logistics') or [])


def customer_pickup_visibility(order, now=None):
    """One-calendar-month read-time visibility, independent of manual show_order.

    'hide' only with affirmative Chile Access-derived pickup evidence and every
    recorded shipment fully picked. Missing/contradictory evidence keeps the
    current public record; never writes any visibility or B2 fields.
    """
    if order.get('all_picked_up') is not True:
        return 'keep_unknown'
    rows = order.get('logistics')
    workflows = order.get('workflows')
    if not isinstance(rows, list) or not rows or not isinstance(workflows, list) or not workflows:
        return 'keep_unknown'
    if any(str(r.get('status') or '').upper() != 'ARRIVED_IQUIQUE'
           or str(r.get('pickup_status') or '').lower() != 'picked_up'
           for r in rows if isinstance(r, dict)) or any(not isinstance(r, dict) for r in rows):
        return 'keep_unknown'
    if any(not isinstance(w, dict) or
           str(w.get('status') or w.get('current_status') or '').upper() != 'COMPLETED'
           for w in workflows):
        return 'keep_unknown'
    raw = str(order.get('last_pickup_date') or '').strip()
    if not raw:
        return 'keep_unknown'
    try:
        from datetime import date
        from calendar import monthrange
        picked = date.fromisoformat(raw[:10])
        if picked.year < 2000:
            return 'keep_unknown'
        clock = now or datetime.now(ZoneInfo('America/Santiago'))
        today = clock.date() if isinstance(clock, datetime) else clock
        if picked > today:
            return 'keep_unknown'
        month0 = picked.month
        year = picked.year + month0 // 12
        month = month0 % 12 + 1
        cutoff = date(year, month, min(picked.day, monthrange(year, month)[1]))
        return 'hide' if today >= cutoff else 'keep_recent_pickup'
    except (TypeError, ValueError):
        return 'keep_unknown'


def retention_reason(order, asset, active=True, now=None):
    """Conservative reasons: an unknown completion/pickup date never authorizes deletion."""
    if pending_pickup(order):
        return 'keep_pending_iquique_pickup'
    if not active:
        return 'candidate_deleted_order'
    if str(order.get('order_status') or '').upper() in CANCELLED:
        return 'candidate_cancelled_order'
    match = source_match(asset, order)
    if match is False:
        workflow = str(asset.get('workflow_key') or '')
        if any(not s.get('sha256') and str(s.get('workflow_key') or '') == workflow for s in order.get('image_sources') or []):
            return 'keep_pending_source_verification'
        if any(d.get('status') != 'ready' and str(d.get('workflow_key') or '') == workflow for d in order.get('documents') or []):
            return 'keep_pending_document_preview'
        return 'candidate_removed_attachment'
    if match is None:
        return 'keep_awaiting_sqlite_manifest'
    workflows = order.get('workflows') or []
    key = str(asset.get('workflow_key') or '')
    relevant = [w for w in workflows if not key or key in {str(w.get('workflow_key') or ''), str(w.get('workflow_number') or '')}]
    if not relevant:
        return 'keep_unknown_workflow'
    now = now or datetime.now(ZoneInfo('America/Santiago'))
    index = now.year * 12 + now.month - 1 - 3
    year, month = divmod(index, 12)
    from calendar import monthrange
    cutoff = now.replace(year=year, month=month + 1, day=min(now.day, monthrange(year, month+1)[1]), hour=0, minute=0, second=0, microsecond=0)
    for workflow in relevant:
        status = str(workflow.get('status') or workflow.get('current_status') or '').upper()
        if status in CANCELLED:
            continue
        if status != 'COMPLETED':
            return 'keep_active_workflow'
        value = workflow.get('last_status_change_date') or workflow.get('status_updated_at')
        try:
            changed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if changed.tzinfo is None:
                changed = changed.replace(tzinfo=ZoneInfo('America/Santiago'))
            if changed >= cutoff:
                return 'keep_recent_completion'
        except (TypeError, ValueError):
            return 'keep_unknown_completion_date'
    return 'candidate_completed_over_three_months'
