# -*- coding: utf-8 -*-
"""Optional isolated TiDB sample-inspection store (never touches Access).

Provide one XW_SCANNER_TIDB_URL (mysql+pymysql://user:pass@host:4000/db)
or the existing XW_SCANNER_TIDB_* variables. TLS certificate and hostname
are verified. DB setup is callable only with authenticated scanner session.
"""
import os
import threading
from urllib.parse import urlsplit, unquote
from datetime import datetime, timezone

# Dedicated DB for this scanner; never write into TiDB Cloud's 'sys'.
DB_NAME = 'xingwang_stock'

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_DONE = False

def _settings():
    url = os.environ.get("XW_SCANNER_TIDB_URL", "").strip()
    if url:
        try:
            parts = urlsplit(url)
            if parts.scheme not in ("mysql", "mysql+pymysql"):
                return None
            host = parts.hostname
            port = parts.port or 4000
            user = unquote(parts.username or "")
            password = unquote(parts.password or "")
            # Ignore the connection dialog's default /sys or /test.
            # All scanner tables live in one dedicated application database.
            if (not host or not user or not password or
                not 0 < port <= 65535):
                return None
            return {"host": host, "port":port, "user":user,
                    "password":password,"database":DB_NAME}
        except (ValueError, TypeError):
            return None
    fields = ("XW_SCANNER_TIDB_HOST", "XW_SCANNER_TIDB_PORT",
              "XW_SCANNER_TIDB_USER", "XW_SCANNER_TIDB_PASSWORD",
              "XW_SCANNER_TIDB_DATABASE")
    if not all(os.environ.get(x, "").strip() for x in fields):
        return None
    try:
        port = int(os.environ["XW_SCANNER_TIDB_PORT"])
        if not 0 < port <= 65535:
            return None
    except ValueError:
        return None
    return {"host":os.environ["XW_SCANNER_TIDB_HOST"].strip(),
            "port":port,
            "user":os.environ["XW_SCANNER_TIDB_USER"].strip(),
            "password":os.environ["XW_SCANNER_TIDB_PASSWORD"],
            "database":DB_NAME}


def configured():
    return _settings() is not None


def _connect(*, bootstrap=False, read_timeout=15, write_timeout=15):
    cfg = _settings()
    if cfg is None:
        raise RuntimeError("TiDB URL or settings not configured")
    if bootstrap:
        # TiDB Starter can start at 'sys' or 'test'. Connect without choosing
        # a database and create this application's database once.
        cfg = {k: v for k, v in cfg.items() if k != "database"}
    import certifi
    import pymysql
    return pymysql.connect(
        **cfg,
        charset="utf8mb4",
        connect_timeout=8,
        read_timeout=read_timeout,
        write_timeout=write_timeout,
        autocommit=False,
        ssl_ca=certifi.where(),
        ssl_verify_cert=True,
        ssl_verify_identity=True,
    )

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS xw_sample_scans (
        scan_id CHAR(32) NOT NULL PRIMARY KEY,
        series VARCHAR(40) NOT NULL,
        checked_at DATETIME(6) NOT NULL,
        sku_count INT NOT NULL,
        missing_count INT NOT NULL,
        device_id VARCHAR(16) NOT NULL,
        KEY idx_series_time (series, checked_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_sample_status (
        sku VARCHAR(40) NOT NULL PRIMARY KEY,
        series VARCHAR(40) NOT NULL,
        missing TINYINT NOT NULL,
        checked_at DATETIME(6) NOT NULL,
        scan_id CHAR(32) NOT NULL,
        KEY idx_series (series)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_sample_scan_items (
        scan_id CHAR(32) NOT NULL,
        sku VARCHAR(40) NOT NULL,
        missing TINYINT NOT NULL,
        PRIMARY KEY (scan_id, sku)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_stock_snapshot (
        sku VARCHAR(128) NOT NULL PRIMARY KEY,
        series VARCHAR(128) NOT NULL,
        stock_rolls DECIMAL(18,3) NULL,
        stock_meters DECIMAL(18,3) NULL,
        is_active TINYINT NOT NULL DEFAULT 1,
        changed_at DATETIME(6) NOT NULL,
        KEY idx_series_active (series, is_active)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS xw_stock_sync_state (
        id TINYINT NOT NULL PRIMARY KEY,
        last_success_utc DATETIME(6) NOT NULL,
        sku_count INT NOT NULL,
        inserted INT NOT NULL,
        updated INT NOT NULL,
        deactivated INT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
)

def _ensure(conn):
    global _SCHEMA_DONE
    if _SCHEMA_DONE:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_DONE:
            return
        with conn.cursor() as cur:
            for ddl in SCHEMA:
                cur.execute(ddl)
        conn.commit()
        _SCHEMA_DONE = True

def read_status(series, skus):
    """Returns prior statuses for the requested real SKU list only."""
    if not skus or len(skus) > 500:
        return {}
    conn = _connect()
    try:
        _ensure(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT sku, missing, checked_at FROM xw_sample_status WHERE series=%s", (series,))
            rows = cur.fetchall()
        allowed = set(skus)
        return {
            sku: {"missing": bool(missing), "checked_at": checked_at.isoformat(timespec="seconds")}
            for sku, missing, checked_at in rows if sku in allowed
        }
    finally:
        conn.close()

def read_order_sample_audit(series, skus):
    """Look up previously saved sample checks for local-order products.

    Does not insert any product into the stock snapshot or record a scan.
    """
    if not isinstance(series, str) or len(series) > 40:
        raise ValueError("Invalid series")
    if not skus or len(skus) > 200 or any(not isinstance(v, str) or len(v) > 40 for v in skus):
        raise ValueError("Invalid sample SKUs")
    conn = _connect()
    try:
        _ensure(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT checked_at, sku_count, missing_count FROM xw_sample_scans "
                "WHERE series=%s ORDER BY checked_at DESC LIMIT 1", (series,)
            )
            previous = cur.fetchone()
            placeholders = ",".join(["%s"] * len(skus))
            cur.execute(
                "SELECT sku, missing, checked_at FROM xw_sample_status "
                "WHERE sku IN (" + placeholders + ")", tuple(skus)
            )
            statuses = {
                sku: {"missing": bool(missing), "checked_at": checked_at.isoformat(timespec="seconds")}
                for sku, missing, checked_at in cur.fetchall() if sku in set(skus)
            }
        return {
            "previous_status": statuses,
            "last_checked_at": previous[0].isoformat(timespec="seconds") + "Z" if previous else None,
            "last_checked_count": previous[1] if previous else None,
            "last_missing_count": previous[2] if previous else None,
        }
    finally:
        conn.close()


# A sample is taken from the most recently committed TiDB inventory, NOT
# from a live V33 bridge.  All timestamps in xw_stock_sync_state are UTC.
STOCK_MAX_AGE_SECONDS = 3600


def _freshness_on_connection(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_success_utc, sku_count "
            "FROM xw_stock_sync_state WHERE id=1"
        )
        row = cur.fetchone()
    if not row or not isinstance(row[0], datetime):
        return {"has_synced": False, "fresh": False,
                "age_seconds": None, "synced_at_utc": None,
                "sku_count": 0, "max_age_seconds": STOCK_MAX_AGE_SECONDS}
    last = row[0]
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    else:
        last = last.astimezone(timezone.utc)
    age = max(0, (datetime.now(timezone.utc) - last).total_seconds())
    return {"has_synced": True, "fresh": age <= STOCK_MAX_AGE_SECONDS,
            "age_seconds": int(age),
            "synced_at_utc": last.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sku_count": int(row[1]),
            "max_age_seconds": STOCK_MAX_AGE_SECONDS}


def stock_freshness():
    """Read last successful sync, never the time of a failed/started update."""
    conn = _connect()
    try:
        _ensure(conn)
        return _freshness_on_connection(conn)
    finally:
        conn.close()



def read_fast_stock(code):
    """Read current TiDB stock snapshot without requiring a recent refresh.

    Only SKU + quantities are in this table; customers, ETA, and history are
    explicitly unavailable here. Readers see one complete table after swap.
    """
    if not isinstance(code, str) or not 1 <= len(code) <= 40:
        raise ValueError("INVALID_PRODUCT_CODE")
    code = code.strip().upper()
    conn = _connect()
    try:
        _ensure(conn)
        state = _freshness_on_connection(conn)
        # Literal prefix, including the regex's permitted underscore.
        pattern = code.replace("!", "!!").replace("_", "!_").replace("%", "!%") + "%"
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sku,stock_rolls,stock_meters "
                "FROM xw_stock_snapshot WHERE is_active=1 AND "
                "(sku=%s OR series=%s OR sku LIKE %s ESCAPE '!') "
                "ORDER BY sku LIMIT 501",
                (code, code, pattern)
            )
            rows = cur.fetchall()
        if len(rows) > 500:
            raise ValueError("TOO_MANY_STOCK_SKUS")
        def total(index):
            values = [row[index] for row in rows]
            if not values:
                return None
            if index == 2:  # Meter summary: NULL contributes zero, source remains NULL.
                return str(sum((x for x in values if x is not None), 0))
            return None if any(x is None for x in values) else str(sum(values, 0))
        return {
            "product_code": code,
            "stock_rolls": total(1), "stock_meters": total(2),
            "incoming_boxes": None,
            "variants": [
                {"code": sku, "stock_rolls": None if rolls is None else str(rolls),
                 "stock_meters": None if meters is None else str(meters),
                 "incoming_boxes": None, "stock_rows": 1}
                for sku, rolls, meters in rows
            ],
            "freshness": state,
            "as_of": state["synced_at_utc"],
            "source": "tidb",
        }
    finally:
        conn.close()


def read_sample_from_snapshot(code, allow_stale=False):
    """Read a single product family from the last verified TiDB snapshot.

    Preserve zero, negative and NULL quantities.  Return no partial family:
    501+ results are rejected before preparing a scan token.
    """
    if not isinstance(code, str) or len(code) > 40:
        raise ValueError("INVALID_PRODUCT_CODE")
    code = code.strip().upper()
    conn = _connect()
    try:
        _ensure(conn)
        freshness = _freshness_on_connection(conn)
        if not freshness["has_synced"] or (not freshness["fresh"] and not allow_stale):
            return {"freshness": freshness, "variants": []}
        # ESCAPE ! is explicit: an underscore in an SKU is a literal
        # underscore, never an accidental SQL LIKE wildcard.
        pattern = code.replace("!", "!!").replace("_", "!_").replace("%", "!%") + "%"
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sku, stock_rolls, stock_meters "
                "FROM xw_stock_snapshot "
                "WHERE is_active=1 AND "
                "(series=%s OR sku=%s OR sku LIKE %s ESCAPE '!') "
                "ORDER BY sku LIMIT 501",
                (code, code, pattern)
            )
            rows = cur.fetchall()
            if len(rows) > 500:
                raise ValueError("TOO_MANY_SAMPLE_SKUS")
            if any(len(str(row[0])) > 40 for row in rows):
                raise ValueError("INVALID_SAMPLE_SKU")
            # A saved scan is an actual audit event; merely looking up this
            # series must never update its audit timestamp.
            cur.execute(
                "SELECT checked_at, sku_count, missing_count "
                "FROM xw_sample_scans WHERE series=%s "
                "ORDER BY checked_at DESC LIMIT 1", (code,)
            )
            latest_scan = cur.fetchone()
            statuses = {}
            if rows:
                keys = [row[0] for row in rows]
                placeholders = ",".join(["%s"] * len(keys))
                cur.execute(
                    "SELECT sku, missing, checked_at FROM xw_sample_status "
                    "WHERE sku IN (" + placeholders + ")", keys
                )
                for sku, missing, checked_at in cur.fetchall():
                    statuses[sku] = {
                        "missing": bool(missing),
                        "checked_at": checked_at.isoformat(timespec="seconds")
                    }
        conn.commit()
        def total(i):
            if i == 2:  # Only arithmetic changes; do not rewrite NULL snapshot values.
                return str(sum((row[i] for row in rows if row[i] is not None), 0))
            return None if any(row[i] is None for row in rows) else str(
                sum((row[i] for row in rows), 0)
            )
        return {
            "freshness": freshness,
            "variants": [
                {"code": sku,
                 "stock_rolls": None if rolls is None else str(rolls),
                 "stock_meters": None if meters is None else str(meters),
                 "incoming_boxes": None, "stock_rows": 1}
                for sku, rolls, meters in rows
            ],
            "previous_status": statuses,
            "last_checked_at": (
                latest_scan[0].isoformat(timespec="seconds") + "Z"
                if latest_scan else None
            ),
            "last_checked_count": latest_scan[1] if latest_scan else None,
            "last_missing_count": latest_scan[2] if latest_scan else None,
            "stock_rolls": total(1) if rows else None,
            "stock_meters": total(2) if rows else None,
        }
    finally:
        conn.close()

def save_scan(scan_id, series, skus, missing, device_id):
    """All-or-nothing transaction; replays with the same scan ID are harmless."""
    if not skus or len(skus) > 500 or len(skus) != len(set(skus)):
        raise ValueError("Invalid sample SKU list")
    if not set(missing).issubset(skus):
        raise ValueError("Invalid missing SKU")
    conn = _connect()
    try:
        _ensure(conn)
        ts = datetime.now(timezone.utc).replace(tzinfo=None)
        absent = set(missing)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sku_count, missing_count, checked_at FROM xw_sample_scans WHERE scan_id=%s",
                (scan_id,)
            )
            duplicate = cur.fetchone()
            if duplicate:
                return {"ok": True, "already_saved": True,
                        "sku_count": duplicate[0], "missing_count": duplicate[1],
                        "checked_at": duplicate[2].isoformat(timespec="seconds")}
            cur.execute(
                "INSERT INTO xw_sample_scans (scan_id,series,checked_at,sku_count,missing_count,device_id) VALUES (%s,%s,%s,%s,%s,%s)",
                (scan_id,series,ts,len(skus),len(absent),device_id)
            )
            cur.executemany(
                "INSERT INTO xw_sample_scan_items (scan_id,sku,missing) VALUES (%s,%s,%s)",
                [(scan_id,sku,int(sku in absent)) for sku in skus]
            )
            cur.executemany(
                """INSERT INTO xw_sample_status (sku,series,missing,checked_at,scan_id)
                   VALUES (%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                     series=VALUES(series), missing=VALUES(missing),
                     checked_at=VALUES(checked_at), scan_id=VALUES(scan_id)""",
                [(sku,series,int(sku in absent),ts,scan_id) for sku in skus]
            )
        conn.commit()
        return {"ok": True, "already_saved": False,
                "sku_count": len(skus), "missing_count":len(absent),
                "checked_at":ts.isoformat(timespec="seconds")}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def stock_breakdown(conn):
    """One read-only aggregate; all active SKUs, incl. zero/negative/NULL."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*),
                   COALESCE(SUM(CASE WHEN stock_rolls > 0 THEN 1 ELSE 0 END),0),
                   COALESCE(SUM(CASE WHEN stock_rolls = 0 THEN 1 ELSE 0 END),0),
                   COALESCE(SUM(CASE WHEN stock_rolls < 0 THEN 1 ELSE 0 END),0),
                   COALESCE(SUM(CASE WHEN stock_rolls IS NULL THEN 1 ELSE 0 END),0)
            FROM xw_stock_snapshot
            WHERE is_active=1
        """)
        total,positive,zero,negative,unknown=cur.fetchone()
    return {"active":int(total), "positive":int(positive),
            "zero":int(zero), "negative":int(negative),
            "null":int(unknown)}


def check_and_initialize():
    """Create dedicated DB and tables, preserving all unrelated schemas."""
    conn = _connect(bootstrap=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS `xingwang_stock` "
                "DEFAULT CHARACTER SET utf8mb4"
            )
        conn.commit()
        conn.select_db(DB_NAME)
        _ensure(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            if cur.fetchone()[0] != 1:
                raise RuntimeError("Database health check failed")
            cur.execute("SELECT COUNT(*) FROM xw_stock_snapshot")
            stock_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM xw_sample_status")
            sample_count = cur.fetchone()[0]
        breakdown = stock_breakdown(conn)
        return {"connected":True, "schema_ready":True,
                "stock_count":int(stock_count),
                "stock_breakdown":breakdown,
                "sample_count":int(sample_count),
                "tables":[
                    "xw_stock_snapshot","xw_stock_sync_state",
                    "xw_sample_status","xw_sample_scans","xw_sample_scan_items"
                ]}
    finally:
        conn.close()
