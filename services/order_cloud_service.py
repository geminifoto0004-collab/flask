"""Cloud publishing storage for ORDER data.

TiDB is the source of truth for what Render may expose to customers.
B2 remains a private object store and is added in the asset phase.
"""
from database import get_db_connection, get_cursor, get_row_dict


def init_order_cloud_tables():
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
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _upsert_customer(cur, key, name, source_site):
    cur.execute("SELECT customer_key FROM cloud_customers WHERE customer_key = ?", (key,))
    if cur.fetchone():
        cur.execute("UPDATE cloud_customers SET customer_name=?, active=TRUE, source_site=?, updated_at=CURRENT_TIMESTAMP WHERE customer_key=?", (name, source_site, key))
    else:
        cur.execute("INSERT INTO cloud_customers (customer_key, customer_name, source_site) VALUES (?, ?, ?)", (key, name, source_site))


def sync_order(payload):
    order_number = str(payload.get('order_number') or '').strip()
    customer_name = str(payload.get('customer_name') or '').strip()
    customer_key = str(payload.get('customer_key') or customer_name).strip()
    source_site = str(payload.get('source_site') or '').strip().upper()[:16] or None
    if not order_number or not customer_name or not customer_key:
        raise ValueError('order_number and customer_name are required')

    workflows = payload.get('workflows') or []
    if not isinstance(workflows, list):
        raise ValueError('workflows must be a list')

    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        _upsert_customer(cur, customer_key, customer_name, source_site)
        cur.execute("SELECT order_number FROM cloud_orders WHERE order_number = ?", (order_number,))
        values = (customer_key, customer_name, payload.get('order_status'), payload.get('order_date'), payload.get('delivery_date'), source_site, order_number)
        if cur.fetchone():
            cur.execute("UPDATE cloud_orders SET customer_key=?, customer_name=?, order_status=?, order_date=?, delivery_date=?, active=TRUE, source_site=?, updated_at=CURRENT_TIMESTAMP WHERE order_number=?", values)
        else:
            cur.execute("INSERT INTO cloud_orders (customer_key, customer_name, order_status, order_date, delivery_date, source_site, order_number) VALUES (?, ?, ?, ?, ?, ?, ?)", values)

        seen = []
        for pos, wf in enumerate(workflows):
            if not isinstance(wf, dict):
                continue
            workflow_key = str(wf.get('workflow_key') or wf.get('id') or f'{order_number}:{pos}').strip()
            seen.append(workflow_key)
            cur.execute("SELECT workflow_key FROM cloud_workflows WHERE workflow_key=?", (workflow_key,))
            vals = (order_number, wf.get('workflow_type') or wf.get('type'), wf.get('status'), wf.get('start_date'), wf.get('completed_date'), wf.get('note'), int(wf.get('sort_order', pos) or 0), workflow_key)
            if cur.fetchone():
                cur.execute("UPDATE cloud_workflows SET order_number=?, workflow_type=?, status=?, start_date=?, completed_date=?, note=?, sort_order=?, active=TRUE, updated_at=CURRENT_TIMESTAMP WHERE workflow_key=?", vals)
            else:
                cur.execute("INSERT INTO cloud_workflows (order_number, workflow_type, status, start_date, completed_date, note, sort_order, workflow_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", vals)

        # A full order snapshot controls what is currently visible in TiDB.
        cur.execute("SELECT workflow_key FROM cloud_workflows WHERE order_number=? AND active=TRUE", (order_number,))
        for row in cur.fetchall():
            data = get_row_dict(row, cur) or {}
            key = str(data.get('workflow_key') or '')
            if key and key not in seen:
                cur.execute("UPDATE cloud_workflows SET active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE workflow_key=?", (key,))

        conn.commit()
        return {'order_number': order_number, 'customer_key': customer_key, 'workflows': len(seen)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_order(order_number):
    conn = get_db_connection()
    cur = get_cursor(conn)
    try:
        cur.execute("SELECT * FROM cloud_orders WHERE order_number=? AND active=TRUE", (order_number,))
        row = cur.fetchone()
        if not row:
            return None
        order = get_row_dict(row, cur)
        cur.execute("SELECT * FROM cloud_workflows WHERE order_number=? AND active=TRUE ORDER BY sort_order, workflow_key", (order_number,))
        order['workflows'] = [get_row_dict(r, cur) for r in cur.fetchall()]
        return order
    finally:
        conn.close()
