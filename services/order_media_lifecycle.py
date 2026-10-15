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


def pending_pickup(order):
    return any(str(r.get('status') or '').upper() == 'ARRIVED_IQUIQUE'
               and str(r.get('pickup_status') or '').lower() != 'picked_up'
               for r in order.get('logistics') or [])


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
