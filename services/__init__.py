# ========== services/__init__.py ==========
"""
Services 包初始化
"""

from .email_service import send_verification_code, verify_code
from .user_service import create_user, verify_password, reset_password

# ORDER public-share fast path.
#
# The original create_live_share() checked customer existence by calling
# get_customer_space(), which loads every order/workflow/history row for the customer.
# For customers with dozens of orders this made token creation slow enough to hit the
# local Render-client timeout.  Token creation only needs to know that the customer
# exists, so replace that existence check with one indexed SELECT.  The public page
# still loads the full customer space later, when the customer actually opens the URL.
from . import order_cloud_service as _order_cloud_service


def _fast_create_live_share(customer_key, source_site=None, expires_hours=24, permanent=False):
    customer_key = str(customer_key or '').strip()
    if not customer_key:
        raise ValueError('customer_key is required')

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


_order_cloud_service.create_live_share = _fast_create_live_share

__all__ = [
    'send_verification_code',
    'verify_code',
    'create_user',
    'verify_password',
    'reset_password'
]
