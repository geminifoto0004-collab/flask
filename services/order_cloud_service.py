"""Cloud publishing storage for ORDER data.

Design rules:
- TiDB stores only customer-safe publishing data.
- Render is the only cloud gateway.
- Clients do not send trusted source identity; the API layer supplies it.
- B2 remains a private object store and is added in the asset phase.
"""
from datetime import datetime, timedelta
import hashlib
import secrets

from database import (
    check_column_exists,
    get_cursor,
    get_db_connection,
    get_row_dict,
)


def _ensure_column(cur, table_name, column_name, definition):
    if not check_column_exists(cur, table_name, column_name):
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_order_cloud_tables():
    """Create/migrate the isolated ORDER cloud publishing tables safely."""
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cloud_customers (
                customer_key VARCHAR(191) PRIMARY KEY,
                customer_name VARCHAR(255) NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                source_site VARCHAR(16) NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cloud_orders (
                order_number VARCHAR(191) PRIMARY KEY,
                customer_key VARCHAR(191) NOT NULL,
                customer_name VARCHAR(255) NOT NULL,
                order_status VARCHAR(191) NULL,
                order_date VARCHAR(32) NULL,
                delivery_date VARCHAR(32) NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                source_site VARCHAR(16) NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_cloud_orders_customer (customer_key)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cloud_workflows (
                workflow_key VARCHAR(191) PRIMARY KEY,
                order_number VARCHAR(191) NOT NULL,
                workflow_type VARCHAR(191) NULL,
                status VARCHAR(191) NULL,
                start_date VARCHAR(32) NULL,
                completed_date VARCHAR(32) NULL,
                note TEXT NULL,
                sort_order INT NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_cloud_workflows_order (order_number)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cloud_workflow_history (
                history_key VARCHAR(191) PRIMARY KEY,
                workflow_key VARCHAR(191) NOT NULL,
                order_number VARCHAR(191) NOT NULL,
                status VARCHAR(191) NULL,
                action_date VARCHAR(32) NULL,
                sort_order INT NOT NULL DEFAULT 0,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_cloud_history_workflow (workflow_key),
                INDEX idx_cloud_history_order (order_number)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cloud_share_tokens (
                token_hash VARCHAR(64) PRIMARY KEY,
                customer_key VARCHAR(191) NOT NULL,
                mode VARCHAR(16) NOT NULL DEFAULT 'LIVE',
                status VARCHAR(16) NOT NULL DEFAULT 'active',
                source_site VARCHAR(16) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NULL,
                INDEX idx_cloud_share_customer (customer_key),
                INDEX idx_cloud_share_status (status)
            )
        """)

        # Safe additive migration from phase 1 to the real ORDER payload shape.
        for name, definition in (
            ("production_type", "VARCHAR(191) NULL"),
            ("product_name", "VARCHAR(255) NULL"),
            ("product_code", "VARCHAR(191) NULL"),
            ("pattern_code", "VARCHAR(191) NULL"),
            ("quantity", "VARCHAR(64) NULL"),
            ("expected_delivery_date", "VARCHAR(32) NULL"),
        ):
            _ensure_column(cur, "cloud_orders", name, definition)

        for name, definition in (
            ("workflow_number", "VARCHAR(191) NULL"),
            ("production_type", "VARCHAR(191) NULL"),
            ("product_name", "VARCHAR(255) NULL"),
            ("product_code", "VARCHAR(191) NULL"),
            ("quantity", "VARCHAR(64) NULL"),
            ("expected_delivery_date", "VARCHAR(32) NULL"),
            ("last_status_change_date", "VARCHAR(32) NULL"),
            ("draft_date", "VARCHAR(32) NULL"),
        ):
            _ensure_column(cur, "cloud_workflows", name, definition)

        # Phase-1 had a generic note column. Internal notes are never cloud data.
        if check_column_exists(cur, "cloud_workflows", "note"):
            cur.execute("UPDATE cloud_workflows SET note=NULL WHERE note IS NOT NULL")

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _upsert_customer(cur, key, name, source_site):
    cur.execute("SELECT customer_key FROM cloud_customers WHERE customer_key = ?", (key,))
    if cur.fetchone():
        cur.execute(
            "UPDATE cloud_customers SET customer_name=?, active=TRUE, source_site=?, updated_at=CURRENT_TIMESTAMP WHERE customer_key=?",
            (name, source_site, key),
        )
    else:
        cur.execute(
            "INSERT INTO cloud_customers (customer_key, customer_name, source_site) VALUES (?, ?, ?)",
            (key, name, source_site),
        )


def sync_order(payload, source_site=None):
    """Upsert one complete customer-safe ORDER snapshot.

    Unknown fields are ignored on purpose. In particular, notes, phones, deposits,
    payment information, internal handler/factory details and arbitrary metadata are
    never written by this function.
    """
    order_number = str(payload.get("order_number") or "").strip()
    customer_name = str(payload.get("customer_name") or "").strip()
    customer_key = str(payload.get("customer_key") or customer_name).strip()
    source_site = (str(source_site or "").strip().upper()[:16] or None)
    if not order_number or not customer_name or not customer_key:
        raise ValueError("order_number and customer_name are required")

    workflows = payload.get("workflows") or []
    if not isinstance(workflows, list):
        raise ValueError("workflows must be a list")

    order_values = {
        "order_status": payload.get("order_status") or payload.get("current_status"),
        "order_date": payload.get("order_date"),
        "expected_delivery_date": payload.get("expected_delivery_date") or payload.get("delivery_date"),
        "production_type": payload.get("production_type"),
        "product_name": payload.get("product_name"),
        "product_code": payload.get("product_code"),
        "pattern_code": payload.get("pattern_code"),
        "quantity": payload.get("quantity"),
    }

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        _upsert_customer(cur, customer_key, customer_name, source_site)
        cur.execute("SELECT order_number FROM cloud_orders WHERE order_number = ?", (order_number,))
        vals = (
            customer_key,
            customer_name,
            order_values["order_status"],
            order_values["order_date"],
            order_values["expected_delivery_date"],
            order_values["production_type"],
            order_values["product_name"],
            order_values["product_code"],
            order_values["pattern_code"],
            str(order_values["quantity"]) if order_values["quantity"] is not None else None,
            source_site,
            order_number,
        )
        if cur.fetchone():
            cur.execute(
                """UPDATE cloud_orders
                   SET customer_key=?, customer_name=?, order_status=?, order_date=?,
                       expected_delivery_date=?, production_type=?, product_name=?,
                       product_code=?, pattern_code=?, quantity=?, active=TRUE,
                       source_site=?, updated_at=CURRENT_TIMESTAMP
                   WHERE order_number=?""",
                vals,
            )
        else:
            cur.execute(
                """INSERT INTO cloud_orders
                   (customer_key, customer_name, order_status, order_date,
                    expected_delivery_date, production_type, product_name,
                    product_code, pattern_code, quantity, source_site, order_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                vals,
            )

        seen_workflows = []
        seen_history = []
        for pos, wf in enumerate(workflows):
            if not isinstance(wf, dict):
                continue
            workflow_number = str(wf.get("workflow_number") or "").strip()
            workflow_key = str(wf.get("workflow_key") or workflow_number or wf.get("id") or f"{order_number}:{pos}").strip()
            seen_workflows.append(workflow_key)
            wf_values = (
                order_number,
                workflow_number or workflow_key,
                wf.get("workflow_type") or wf.get("production_type") or wf.get("type"),
                wf.get("status") or wf.get("current_status"),
                wf.get("production_type"),
                wf.get("product_name"),
                wf.get("product_code"),
                str(wf.get("quantity")) if wf.get("quantity") is not None else None,
                wf.get("expected_delivery_date"),
                wf.get("last_status_change_date"),
                wf.get("draft_date"),
                int(wf.get("sort_order", pos) or 0),
                workflow_key,
            )
            cur.execute("SELECT workflow_key FROM cloud_workflows WHERE workflow_key=?", (workflow_key,))
            if cur.fetchone():
                cur.execute(
                    """UPDATE cloud_workflows
                       SET order_number=?, workflow_number=?, workflow_type=?, status=?,
                           production_type=?, product_name=?, product_code=?, quantity=?,
                           expected_delivery_date=?, last_status_change_date=?, draft_date=?,
                           sort_order=?, active=TRUE, note=NULL, updated_at=CURRENT_TIMESTAMP
                       WHERE workflow_key=?""",
                    wf_values,
                )
            else:
                cur.execute(
                    """INSERT INTO cloud_workflows
                       (order_number, workflow_number, workflow_type, status,
                        production_type, product_name, product_code, quantity,
                        expected_delivery_date, last_status_change_date, draft_date,
                        sort_order, workflow_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    wf_values,
                )

            timeline = wf.get("timeline") or wf.get("history") or []
            if not isinstance(timeline, list):
                timeline = []
            for hpos, item in enumerate(timeline):
                if not isinstance(item, dict):
                    continue
                history_key = str(
                    item.get("history_key")
                    or item.get("id")
                    or f"{workflow_key}:{hpos}:{item.get('status') or item.get('to_status') or ''}:{item.get('action_date') or ''}"
                ).strip()
                seen_history.append(history_key)
                history_values = (
                    workflow_key,
                    order_number,
                    item.get("status") or item.get("to_status"),
                    item.get("action_date"),
                    int(item.get("sort_order", hpos) or 0),
                    history_key,
                )
                cur.execute("SELECT history_key FROM cloud_workflow_history WHERE history_key=?", (history_key,))
                if cur.fetchone():
                    cur.execute(
                        """UPDATE cloud_workflow_history
                           SET workflow_key=?, order_number=?, status=?, action_date=?,
                               sort_order=?, active=TRUE, updated_at=CURRENT_TIMESTAMP
                           WHERE history_key=?""",
                        history_values,
                    )
                else:
                    cur.execute(
                        """INSERT INTO cloud_workflow_history
                           (workflow_key, order_number, status, action_date, sort_order, history_key)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        history_values,
                    )

        # Full snapshots determine logical visibility. B2 cleanup is separate/later.
        cur.execute("SELECT workflow_key FROM cloud_workflows WHERE order_number=? AND active=TRUE", (order_number,))
        for row in cur.fetchall():
            data = get_row_dict(row, cur) or {}
            key = str(data.get("workflow_key") or "")
            if key and key not in seen_workflows:
                cur.execute("UPDATE cloud_workflows SET active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE workflow_key=?", (key,))

        cur.execute("SELECT history_key FROM cloud_workflow_history WHERE order_number=? AND active=TRUE", (order_number,))
        for row in cur.fetchall():
            data = get_row_dict(row, cur) or {}
            key = str(data.get("history_key") or "")
            if key and key not in seen_history:
                cur.execute("UPDATE cloud_workflow_history SET active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE history_key=?", (key,))

        conn.commit()
        return {
            "order_number": order_number,
            "customer_key": customer_key,
            "workflows": len(seen_workflows),
            "timeline_items": len(seen_history),
            "source_site": source_site,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _safe_order_dict(row, cur):
    return get_row_dict(row, cur) if row else None


def get_order(order_number):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT order_number, customer_key, customer_name, order_status, order_date,
                      expected_delivery_date, production_type, product_name, product_code,
                      pattern_code, quantity, active, source_site, updated_at
               FROM cloud_orders WHERE order_number=? AND active=TRUE""",
            (order_number,),
        )
        row = cur.fetchone()
        if not row:
            return None
        order = _safe_order_dict(row, cur)
        cur.execute(
            """SELECT workflow_key, workflow_number, order_number, workflow_type, status,
                      production_type, product_name, product_code, quantity,
                      expected_delivery_date, last_status_change_date, draft_date,
                      sort_order, active, updated_at
               FROM cloud_workflows
               WHERE order_number=? AND active=TRUE
               ORDER BY sort_order, workflow_key""",
            (order_number,),
        )
        workflows = []
        for wf_row in cur.fetchall():
            wf = _safe_order_dict(wf_row, cur)
            cur.execute(
                """SELECT history_key, status, action_date, sort_order
                   FROM cloud_workflow_history
                   WHERE workflow_key=? AND active=TRUE
                   ORDER BY sort_order, action_date, history_key""",
                (wf["workflow_key"],),
            )
            wf["timeline"] = [_safe_order_dict(r, cur) for r in cur.fetchall()]
            workflows.append(wf)
        order["workflows"] = workflows
        return order
    finally:
        conn.close()


def get_customer_space(customer_key):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            "SELECT customer_key, customer_name, updated_at FROM cloud_customers WHERE customer_key=? AND active=TRUE",
            (customer_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        customer = _safe_order_dict(row, cur)
        cur.execute(
            "SELECT order_number FROM cloud_orders WHERE customer_key=? AND active=TRUE ORDER BY order_date DESC, order_number DESC",
            (customer_key,),
        )
        order_numbers = [(_safe_order_dict(r, cur) or {}).get("order_number") for r in cur.fetchall()]
    finally:
        conn.close()

    orders = [get_order(number) for number in order_numbers if number]
    return {"customer": customer, "orders": [x for x in orders if x]}


def create_live_share(customer_key, source_site=None, expires_hours=24, permanent=False):
    customer_key = str(customer_key or "").strip()
    if not customer_key:
        raise ValueError("customer_key is required")
    if get_customer_space(customer_key) is None:
        raise ValueError("customer not found")

    if permanent:
        expires_at = None
    else:
        try:
            hours = int(expires_hours or 24)
        except (TypeError, ValueError):
            raise ValueError("expires_hours must be an integer")
        if hours < 1 or hours > 24 * 365:
            raise ValueError("expires_hours must be between 1 and 8760")
        expires_at = datetime.utcnow() + timedelta(hours=hours)

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """INSERT INTO cloud_share_tokens
               (token_hash, customer_key, mode, status, source_site, expires_at)
               VALUES (?, ?, 'LIVE', 'active', ?, ?)""",
            (token_hash, customer_key, (str(source_site or "").upper()[:16] or None), expires_at),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"token": raw_token, "customer_key": customer_key, "expires_at": expires_at}


def resolve_live_share(raw_token):
    raw_token = str(raw_token or "").strip()
    if not raw_token:
        return None, "not_found"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute(
            """SELECT token_hash, customer_key, mode, status, source_site, created_at, expires_at
               FROM cloud_share_tokens WHERE token_hash=?""",
            (token_hash,),
        )
        row = cur.fetchone()
        if not row:
            return None, "not_found"
        share = _safe_order_dict(row, cur)
    finally:
        conn.close()

    if share.get("status") != "active":
        return share, "revoked"
    expires_at = share.get("expires_at")
    if expires_at:
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                expires_at = None
        if expires_at and datetime.utcnow() >= expires_at:
            return share, "expired"
    return share, "active"


def revoke_live_share(raw_token):
    raw_token = str(raw_token or "").strip()
    if not raw_token:
        return False
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute("UPDATE cloud_share_tokens SET status='revoked' WHERE token_hash=? AND status='active'", (token_hash,))
        changed = bool(cur.rowcount)
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
