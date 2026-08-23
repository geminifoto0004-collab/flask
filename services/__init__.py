# ========== services/__init__.py ==========
"""
Services 包初始化
"""

from .email_service import send_verification_code, verify_code
from .user_service import create_user, verify_password, reset_password

# ORDER public-share fast paths.
#
# The legacy cloud service is correct but some read paths use N+1 queries. Large
# customers (dozens of orders, workflows and history rows) can therefore exceed the
# Render request timeout. Keep the storage schema/business behaviour unchanged and
# replace only the two expensive public-share read/create paths with bounded-query
# implementations.
from . import order_cloud_service as _order_cloud_service


def _fast_create_live_share(customer_key, source_site=None, expires_hours=24, permanent=False):
    customer_key = str(customer_key or '').strip()
    if not customer_key:
        raise ValueError('customer_key is required')

    # Token creation only needs an existence check. Do not load the full customer
    # space here; the public GET will load it when someone actually opens the URL.
    conn = _order_cloud_service.get_db_connection()
    cur = _order_cloud_service.get_cursor(conn)
    try:
        cur.execute(
            'SELECT customer_key FROM cloud_customers WHERE customer_key=? AND active=TRUE LIMIT 1',
            (customer_key,),
        )
        if not cur.fetchone():
            raise ValueError('customer not found')
    finally:
        conn.close()

    if permanent:
        expires_at = None
    else:
        try:
            hours = int(expires_hours or 24)
        except (TypeError, ValueError):
            raise ValueError('expires_hours must be an integer')
        if hours < 1 or hours > 24 * 365:
            raise ValueError('expires_hours must be between 1 and 8760')
        expires_at = _order_cloud_service.datetime.utcnow() + _order_cloud_service.timedelta(hours=hours)

    raw_token = _order_cloud_service.secrets.token_urlsafe(32)
    token_hash = _order_cloud_service.hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    conn = _order_cloud_service.get_db_connection()
    cur = _order_cloud_service.get_cursor(conn)
    try:
        cur.execute(
            """INSERT INTO cloud_share_tokens
               (token_hash, customer_key, mode, status, source_site, expires_at)
               VALUES (?, ?, 'LIVE', 'active', ?, ?)""",
            (
                token_hash,
                customer_key,
                (str(source_site or '').upper()[:16] or None),
                expires_at,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {'token': raw_token, 'customer_key': customer_key, 'expires_at': expires_at}


def _fast_get_customer_space(customer_key):
    """Load one public customer space in a fixed number of SQL queries.

    Legacy get_customer_space() selected order numbers and then called get_order()
    once per order; get_order() in turn queried history once per workflow. A customer
    with 42 orders could therefore produce hundreds of TiDB round-trips. This version
    fetches customer, orders, workflows and history in four indexed queries and groups
    rows in Python while preserving the original response shape.
    """
    customer_key = str(customer_key or '').strip()
    if not customer_key:
        return None

    conn = _order_cloud_service.get_db_connection()
    cur = _order_cloud_service.get_cursor(conn)
    try:
        cur.execute(
            "SELECT customer_key, customer_name, updated_at "
            "FROM cloud_customers WHERE customer_key=? AND active=TRUE LIMIT 1",
            (customer_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        customer = _order_cloud_service.get_row_dict(row, cur)

        cur.execute(
            """SELECT order_number, customer_key, customer_name, order_status, order_date,
                      expected_delivery_date, production_type, product_name, product_code,
                      pattern_code, quantity, active, source_site, updated_at
               FROM cloud_orders
               WHERE customer_key=? AND active=TRUE
               ORDER BY order_date DESC, order_number DESC""",
            (customer_key,),
        )
        orders = [_order_cloud_service.get_row_dict(r, cur) for r in cur.fetchall()]
        if not orders:
            return {'customer': customer, 'orders': []}

        by_order = {str(order.get('order_number') or ''): order for order in orders}
        for order in orders:
            order['workflows'] = []

        cur.execute(
            """SELECT w.workflow_key, w.workflow_number, w.order_number, w.workflow_type,
                      w.status, w.production_type, w.product_name, w.product_code,
                      w.quantity, w.expected_delivery_date, w.last_status_change_date,
                      w.draft_date, w.sort_order, w.active, w.updated_at
               FROM cloud_workflows w
               INNER JOIN cloud_orders o ON o.order_number=w.order_number
               WHERE o.customer_key=? AND o.active=TRUE AND w.active=TRUE
               ORDER BY w.order_number, w.sort_order, w.workflow_key""",
            (customer_key,),
        )
        workflows = [_order_cloud_service.get_row_dict(r, cur) for r in cur.fetchall()]
        by_workflow = {}
        for wf in workflows:
            wf['timeline'] = []
            wf_key = str(wf.get('workflow_key') or '')
            if wf_key:
                by_workflow[wf_key] = wf
            parent = by_order.get(str(wf.get('order_number') or ''))
            if parent is not None:
                parent['workflows'].append(wf)

        if by_workflow:
            cur.execute(
                """SELECT h.history_key, h.workflow_key, h.order_number, h.status,
                          h.action_date, h.sort_order
                   FROM cloud_workflow_history h
                   INNER JOIN cloud_orders o ON o.order_number=h.order_number
                   WHERE o.customer_key=? AND o.active=TRUE AND h.active=TRUE
                   ORDER BY h.order_number, h.workflow_key, h.sort_order,
                            h.action_date, h.history_key""",
                (customer_key,),
            )
            for r in cur.fetchall():
                item = _order_cloud_service.get_row_dict(r, cur)
                parent = by_workflow.get(str(item.get('workflow_key') or ''))
                if parent is not None:
                    parent['timeline'].append(item)

        return {'customer': customer, 'orders': orders}
    finally:
        conn.close()


_order_cloud_service.create_live_share = _fast_create_live_share
_order_cloud_service.get_customer_space = _fast_get_customer_space

# Register the protected short-lived direct-B2 upload signer on b2_test_bp before
# app.py registers that blueprint. No B2 credential leaves Render.
from . import order_cloud_direct_b2 as _order_cloud_direct_b2  # noqa: E402,F401

# Intercept public ORDER share routes before the legacy handlers: persist each link's
# scope, filter old/cancelled rows per token, serve cached thumbnails, and redirect
# authorized WEB-image reads directly to short-lived private B2 URLs.
from . import order_public_share_fast as _order_public_share_fast  # noqa: E402,F401

# Keep the chunked full-mirror finalize HTTP request short.  Expensive old-table cleanup
# is deliberately deferred so Render/Gunicorn does not terminate finalize with an empty 502.
from . import order_full_mirror_finalize_fast as _order_full_mirror_finalize_fast  # noqa: E402,F401

__all__ = [
    'send_verification_code',
    'verify_code',
    'create_user',
    'verify_password',
    'reset_password'
]
