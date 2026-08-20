"""Dedicated TiDB connection for the unified ORDER mirror.

The parent Flask application already has its own TiDB tables (including a users
 table). ORDER therefore gets a separate logical database on the same TiDB cluster
instead of reusing the parent's current database. This lets ORDER keep its original
logical table names: users, orders, workflows, notifications, etc.

No credentials are stored here. Existing DATABASE_URL / MYSQL_* / DB_* environment
variables are reused, while ORDER_TIDB_DATABASE optionally overrides the logical
ORDER database name. The default is ``order_tracking``.
"""
from __future__ import annotations

import os
import re
import threading
import urllib.parse

from config import config

_DB_NAME = (os.environ.get('ORDER_TIDB_DATABASE') or 'order_tracking').strip()
if not re.fullmatch(r'[A-Za-z0-9_]+', _DB_NAME):
    raise RuntimeError('ORDER_TIDB_DATABASE may contain only letters, digits and underscore')

_init_lock = threading.Lock()
_database_ready = False


def _base_config(database=None):
    if config.DATABASE_URL:
        parsed = urllib.parse.urlparse(config.DATABASE_URL)
        cfg = {
            'host': parsed.hostname or config.MYSQL_HOST,
            'port': parsed.port or config.MYSQL_PORT,
            'user': parsed.username or config.MYSQL_USER,
            'password': parsed.password or config.MYSQL_PASSWORD,
            'charset': 'utf8mb4',
            'autocommit': False,
            'connect_timeout': 10,
            'read_timeout': 45,
            'write_timeout': 45,
        }
    else:
        cfg = {
            'host': config.MYSQL_HOST,
            'port': config.MYSQL_PORT,
            'user': config.MYSQL_USER,
            'password': config.MYSQL_PASSWORD,
            'charset': 'utf8mb4',
            'autocommit': False,
            'connect_timeout': 10,
            'read_timeout': 45,
            'write_timeout': 45,
        }
    if database:
        cfg['database'] = database
    if 'tidbcloud.com' in str(cfg.get('host') or '').lower():
        cfg['ssl'] = {'check_hostname': False}
    return cfg


def _connect(database=None):
    import pymysql
    import pymysql.cursors

    cfg = _base_config(database=database)
    cfg['cursorclass'] = pymysql.cursors.DictCursor
    return pymysql.connect(**cfg)


def ensure_order_database():
    """Create the isolated ORDER logical database once per process."""
    global _database_ready
    if _database_ready:
        return _DB_NAME
    with _init_lock:
        if _database_ready:
            return _DB_NAME
        # Connect without selecting the parent Flask database so USE/CREATE can
        # never alter a pooled parent connection.
        conn = _connect(database=None)
        try:
            cur = conn.cursor()
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{_DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
        finally:
            conn.close()
        _database_ready = True
    return _DB_NAME


def get_order_tidb_connection():
    """Return a fresh dedicated PyMySQL DictCursor connection for ORDER."""
    ensure_order_database()
    return _connect(database=_DB_NAME)


def order_database_name():
    return _DB_NAME
