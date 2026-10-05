import ast
import hashlib
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

    def test_existing_legacy_source_is_visible_through_global_order_gate(self):
        self.create(source_site='CL')
        result = self.create(source_site='ORDER')
        self.assertTrue(result['reused_token'])

    def test_final_create_route_passes_requested_token_and_reports_conflicts(self):
        self._check_create_route('order_share_image_source_patch.py')

    def test_visibility_create_route_passes_requested_token_and_reports_conflicts(self):
        self._check_create_route('order_share_visibility_live_patch.py')

    def _check_create_route(self, filename):
        from flask import Flask, request, jsonify
        path=ROOT/'services'/filename
        node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef)
                  and n.name=='_create_scoped_share')
        cloud=types.ModuleType('services.order_cloud_service');cloud.create_live_share=self.control.create_live_share
        control=types.ModuleType('services.order_share_create_control');control.ShareCreateConflict=self.control.ShareCreateConflict
        scope={'request':request,'jsonify':jsonify,'hashlib':hashlib,
               '_order_cloud_auth_source':lambda:('ORDER',None),'_ensure_columns':lambda:None,
               '_scope':lambda value:value or 'current','_mode':lambda value:value or 'simple',
               '_flags':lambda p:(bool(p.get('show_pdf_pages',True)),bool(p.get('allow_report_pdf_download')),bool(p.get('show_images',True))),
               '_drop_caches':lambda *args:(_ for _ in ()).throw(RuntimeError('busy')),
               '_bool_default':lambda value,default=True: default if value is None else bool(value)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(path),'exec'),scope)
        app=Flask(__name__);app.add_url_rule('/create',view_func=scope['_create_scoped_share'],methods=['POST'])
        with patch.dict(sys.modules,{'services.order_cloud_service':cloud,'services.order_share_create_control':control}):
            client=app.test_client()
            payload={'customer_key':'SERGIO','requested_token':'a'*43,'show_images':False}
            first=client.post('/create',json=payload)
            self.assertEqual(first.status_code,200)
            self.assertTrue(first.get_json()['result']['share_url'].endswith('a'*43))
            second=client.post('/create',json=dict(payload,show_images=True))
            self.assertFalse(second.get_json()['result']['show_images'])
            self.assertTrue(second.get_json()['result']['reused_token'])
            self.assertEqual(client.post('/create',json=dict(payload,customer_key='OTHER')).status_code,409)
            self.assertEqual(client.post('/create',json=dict(payload,requested_token='bad')).status_code,400)
