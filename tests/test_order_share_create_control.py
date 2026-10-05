from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'db.sqlite')
        conn = self.connect()
        conn.executescript('''CREATE TABLE cloud_customers(customer_key TEXT PRIMARY KEY, active INTEGER);
        INSERT INTO cloud_customers VALUES('SERGIO',1),('OTHER',1);
        CREATE TABLE cloud_share_tokens(token_hash TEXT PRIMARY KEY, customer_key TEXT, mode TEXT,
        status TEXT, source_site TEXT, history_scope TEXT, status_filter_mode TEXT, show_pdf_pages INTEGER,
        allow_report_pdf_download INTEGER, show_images INTEGER, show_workflow_images INTEGER,
        include_cancelled INTEGER, expires_at TEXT);''')
        conn.close()
        database = types.ModuleType('database')
        database.get_db_connection = self.connect
        database.get_cursor = lambda conn: conn.cursor()
        database.get_row_dict = lambda row, cur: dict(row)
        with patch.dict(sys.modules, {'database': database}):
            self.control = load_module('control_v110_test', ROOT / 'services/order_share_create_control.py')

    def tearDown(self):
        self.temp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, **kwargs):
        return self.control.create_live_share('SERGIO', requested_token='a' * 43, **kwargs)

    def test_same_token_concurrently_creates_one_row_and_keeps_original_settings(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.create(show_images=False, permanent=True), range(4)))
        conn = self.connect()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM cloud_share_tokens').fetchone()[0], 1)
        conn.close()
        self.assertEqual(len({r['share_id'] for r in results}), 1)
        self.assertEqual(sum(not r['reused_token'] for r in results), 1)
        repeated = self.create(show_images=True, permanent=False)
        self.assertFalse(repeated['show_images'])
        self.assertIsNone(repeated['expires_at'])

    def test_revoked_expired_and_other_customer_are_conflicts(self):
        self.create()
        with self.assertRaises(self.control.ShareCreateConflict):
            self.control.create_live_share('OTHER', requested_token='a' * 43)
        for status, expiry in [('revoked', None), ('active', datetime.utcnow() - timedelta(days=1))]:
            conn = self.connect()
            conn.execute('UPDATE cloud_share_tokens SET status=?,expires_at=?', (status, expiry))
            conn.commit(); conn.close()
            with self.assertRaises(self.control.ShareCreateConflict):
                self.create()

    def test_missing_customer_and_bad_token_do_not_insert(self):
        with self.assertRaises(ValueError):
            self.control.create_live_share('MISSING', requested_token='b' * 43)
        for token in ['short', '../' + 'a'*40, 'a'*129, 100]:
            with self.assertRaises(ValueError):
                self.control.create_live_share('SERGIO', requested_token=token)
        conn = self.connect()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM cloud_share_tokens').fetchone()[0], 0)
        conn.close()
