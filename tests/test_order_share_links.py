"""Verify directory links retain existing share authorization and lifecycle."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import unittest
from datetime import datetime, timedelta
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('directory_links_test', ROOT/'services/order_share_links.py')
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)

class DirectoryLinkTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__);links._KEY=b'test-only-stable-signing-key'
        self.raw='existing-public-token';self.hash=hashlib.sha256(self.raw.encode()).hexdigest()

    def test_same_share_legacy_and_signed_tampering_and_key_change(self):
        with self.app.app_context():
            token=links.share_link_token(self.hash)
            self.assertEqual(links.share_token_hash(token),self.hash)
            self.assertEqual(links.share_token_hash(self.raw),self.hash)
            self.assertEqual(links.share_link_token(self.hash),token)
            self.assertNotEqual(links.share_token_hash(token[:-1]+('A' if token[-1]!='A' else 'B')),self.hash)
            self.assertNotEqual(links.share_token_hash(token.replace(self.hash,'b'*64)), 'b'*64)
            links._KEY=b'different-key'
            self.assertNotEqual(links.share_token_hash(token),self.hash)

    def test_signing_independent_of_default_flask_key_and_request_context(self):
        self.app.secret_key='dev-secret-key-change-in-production'
        token=links.share_link_token(self.hash)
        self.assertEqual(links.share_token_hash(token),self.hash)
        with self.app.app_context():
            self.assertEqual(links.share_token_hash(token),self.hash)

    def test_signed_token_resolver_uses_existing_visibility_expiry_and_revocation(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        conn.executescript('CREATE TABLE cloud_share_tokens(token_hash TEXT, customer_key TEXT, mode TEXT, status TEXT, source_site TEXT, created_at TEXT, expires_at TEXT, history_scope TEXT, status_filter_mode TEXT, include_cancelled INTEGER, show_pdf_pages INTEGER, allow_report_pdf_download INTEGER, show_images INTEGER, show_workflow_images INTEGER); CREATE TABLE cloud_share_order_visibility(token_hash TEXT,order_number TEXT,show_order INTEGER,show_images INTEGER,show_workflow_images INTEGER);')
        conn.execute('INSERT INTO cloud_share_tokens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(self.hash,'KC','LIVE','active','ORDER',None,None,'current','simple',0,1,0,1,0))
        conn.execute('INSERT INTO cloud_share_order_visibility VALUES (?,?,?,?,?)',(self.hash,'1008000',0,0,0))
        # Execute actual public resolver against a small database without startup hooks.
        node=next(n for n in ast.parse((ROOT/'services/order_public_share_fast.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='_resolve_share')
        class Connection:
            def cursor(self):return conn.cursor()
            def close(self):pass
        scope={'share_token_hash':links.share_token_hash,'_share_cache':{},'_cache_get':lambda *a:None,'_cache_put':lambda *a:None,'_ensure_share_columns':lambda:None,'get_db_connection':Connection,'get_cursor':lambda c:c.cursor(),'get_row_dict':lambda r,c:dict(r),'_scope':lambda s:s,'_status_filter_mode':lambda s:s,'datetime':datetime,'_SHARE_CACHE_TTL':1}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'resolver','exec'),scope)
        with self.app.app_context():
            token=links.share_link_token(self.hash)
            share,state=scope['_resolve_share'](token)
            self.assertEqual(state,'active');self.assertEqual(share['customer_key'],'KC');self.assertFalse(share['order_visibility']['1008000']['show_order'])
            conn.execute('UPDATE cloud_share_tokens SET expires_at=?',((datetime.utcnow()-timedelta(days=1)).isoformat(),))
            self.assertEqual(scope['_resolve_share'](token)[1],'expired')
            conn.execute("UPDATE cloud_share_tokens SET status='revoked',expires_at=NULL")
            self.assertEqual(scope['_resolve_share'](token)[1],'revoked')
            self.assertEqual(conn.execute('SELECT count(*) FROM cloud_share_tokens').fetchone()[0],1)
        conn.close()
