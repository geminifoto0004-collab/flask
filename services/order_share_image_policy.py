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
                order['assets'] = [a for a in order.get('assets') or [] if asset_allowed(a, settings)]
    return space
