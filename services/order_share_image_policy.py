def source_match(asset, order):
    if not order.get('image_sources_authoritative'):
        return None
    key = (str(asset.get('workflow_key') or ''), str(asset.get('sha256') or ''))
    matches = [s for s in order.get('image_sources') or []
               if (str(s.get('workflow_key') or ''), str(s.get('sha256') or '')) == key]
    return max(matches, key=lambda s: int(s.get('uploaded_at_epoch') or 0)) if matches else False


"""Shared image-source policy for public HTML and authorized media reads."""


def bool_default(value, default=True):
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() not in {'0', 'false', 'no', 'off', ''}
    return bool(value)


def _order_override(settings, order_number):
    settings = settings or {}
    visibility = settings.get('order_visibility') or {}
    if not isinstance(visibility, dict):
        return {}
    key = str(order_number or '').strip()
    value = visibility.get(key) or {}
    return value if isinstance(value, dict) else {}


def asset_allowed(asset, settings):
    if not isinstance(asset, dict):
        return True
    settings = settings or {}
    override = _order_override(settings, asset.get('order_number'))
    if override and override.get('show_order') is False:
        return False

    is_pdf_page = str(asset.get('asset_kind') or '').strip().upper() == 'PDF_PAGE'
    if is_pdf_page and not bool_default(settings.get('show_pdf_pages')):
        return False
    is_image = (
        str(asset.get('asset_type') or '').strip().upper() == 'IMAGE'
        or str(asset.get('content_type') or '').lower().startswith('image/')
        or is_pdf_page
    )
    if not is_image:
        return True

    setting = 'show_workflow_images' if str(asset.get('workflow_key') or '').strip() else 'show_images'
    if setting in override and override.get(setting) is not None:
        return bool_default(override.get(setting), default=True)
    return bool_default(settings.get(setting))


def filter_assets_in_space(space, settings):
    """Filter a request-owned copy; never pass a shared customer snapshot here."""
    if isinstance(space, dict):
        for order in space.get('orders') or []:
            if isinstance(order, dict):
                order['assets'] = [a for a in order.get('assets') or [] if source_match(a, order) is not False]
                pdf_shas = {str(p.get('sha256') or '') for d in order.get('documents') or [] for p in d.get('pages') or []}
                all_pdf_shas = set(order.get('pdf_page_hashes') or []) | pdf_shas
                for asset in order.get('assets') or []:
                    if str(asset.get('sha256') or '') in all_pdf_shas:
                        asset['asset_kind'] = 'PDF_PAGE'
                order['assets'] = [a for a in order.get('assets') or [] if asset_allowed(a, settings) and (str(a.get('sha256') or '') not in all_pdf_shas or str(a.get('sha256') or '') in pdf_shas)]
                order['documents'] = [d for d in order.get('documents') or [] if asset_allowed({'order_number': order.get('order_number'), 'workflow_key': d.get('workflow_key'), 'asset_kind': 'PDF_PAGE'}, settings)]
    return space
