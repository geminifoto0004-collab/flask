"""Persisted-page parity and token policy isolation, without production databases."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
import threading
import time
from types import SimpleNamespace
from test_order_share_cache_lock import cache_scope

ROOT = Path(__file__).resolve().parents[1]

def functions(path, names, scope):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), scope)
    return scope

class ParityTests(unittest.TestCase):
    def test_51_orders_and_extra_workflow_cards_are_not_truncated(self):
        scope = functions('services/order_cloud_customer_reconcile.py', {'_snapshot_manifest'}, {'json': json})
        orders = [{'order_number': str(i), 'workflows': [{'workflow_number': f'{i}-1'}]} for i in range(51)]
        orders[-1]['workflows'].append({'workflow_number': '50-2'})
        hashes = {str(i): 'digest-' + str(i) for i in range(51)}
        numbers, cards, actual = scope['_snapshot_manifest'](json.dumps({'space': {'orders': orders}, 'source_payload_hashes': hashes}))
        self.assertEqual(len(numbers), 51)
        self.assertEqual(len(cards), 52)
        self.assertIn('50-2', cards)
        self.assertEqual(actual, hashes)

    def test_corrupt_snapshot_is_unknown_and_empty_snapshot_is_empty(self):
        fn = functions('services/order_cloud_customer_reconcile.py', {'_snapshot_manifest'}, {'json': json})['_snapshot_manifest']
        for invalid in ('{broken', '[]', '{"space":{"orders":"bad"}}'):
            self.assertEqual(fn(invalid), (None, None, None))
        self.assertEqual(fn(None), ([], [], None))

    def test_same_customer_different_tokens_and_hide_unhide_get_distinct_html(self):
        scope = cache_scope()
        fn = scope['_variant_key']
        share = {'customer_key': 'CLIENT A', 'token_hash': 'a' * 64, 'order_visibility': {}}
        original = fn(share)
        hidden = fn(dict(share, order_visibility={'1007705': {'show_order': False}}))
        other = fn(dict(share, token_hash='b' * 64))
        self.assertEqual(len({original, hidden, other}), 3)
        self.assertEqual(fn(dict(share, order_visibility={})), original)
        self.assertEqual(fn({'customer_key': 'CLIENT A'}), '')

    def test_snapshot_hash_certifies_raw_source_not_normalized_display(self):
        source = {'order_number': '1007705', 'remark': 'new', 'logistics': [{'eta': '2026-10-20'}]}
        row = {'order_number': '1007705', 'customer_name': 'CLIENT A', 'render_payload': json.dumps(source)}
        page = type('Page', (), {'_decode_payload': staticmethod(json.loads),
            '_normalize_order_payload': staticmethod(lambda p, r: dict(p, assets=[], display_only=True))})
        scope = functions('services/order_customer_share_snapshot.py', {'_build_bundle'},
            {'json': json, 'hashlib': hashlib, '_page': page, '_load_build_rows': lambda c: ([row], [])})
        result = scope['_build_bundle']('CLIENT A')
        canonical = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
        self.assertEqual(result['source_payload_hashes']['1007705'], hashlib.sha256(canonical.encode()).hexdigest())

class RefreshTests(unittest.TestCase):
    def test_busy_customer_does_not_hold_a_request_indefinitely(self):
        entered=threading.Event(); release=threading.Event()
        def build(customer):
            entered.set(); release.wait(2); return {'source_payload_hashes': {}, 'data_mode':'test'}
        scope=functions('services/order_customer_share_snapshot.py', {'rebuild_snapshot'},
            {'threading':threading,'time':time,'_TIMER_LOCK':threading.Lock(),
             '_BUILD_LOCKS':{},'_BUILD_SLOTS':threading.BoundedSemaphore(2),
             '_build_bundle':build,'_persist_snapshot':lambda *a:None,'_invalidate_local_cache':lambda *a:None})
        worker=threading.Thread(target=scope['rebuild_snapshot'],args=('CLIENT',));worker.start()
        try:
            self.assertTrue(entered.wait(1)); start=time.monotonic()
            with self.assertRaisesRegex(RuntimeError,'already running'):
                scope['rebuild_snapshot']('CLIENT')
            self.assertLess(time.monotonic()-start,.5)
        finally: release.set();worker.join(2)
        self.assertTrue(scope['_BUILD_SLOTS'].acquire(blocking=False))
        scope['_BUILD_SLOTS'].release()

    def test_failed_refresh_keeps_a_retry_and_preserves_newer_mutations(self):
        current=object(); scheduled=[]
        class Timer:
            def __init__(self,delay,fn,args): self.delay=delay;self.fn=fn;self.args=args;scheduled.append(self)
            def start(self): self.started=True
        def fail(customer): raise RuntimeError('temporary read timeout')
        scope=functions('services/order_customer_share_snapshot.py', {'_refresh_worker'},
            {'threading':SimpleNamespace(current_thread=lambda:current,Timer=Timer),
             '_TIMER_LOCK':threading.Lock(),'_REFRESH_TIMERS':{'CLIENT':current},
             '_BUILD_FAILURES':{},'rebuild_snapshot':fail})
        scope['_refresh_worker']('CLIENT')
        self.assertEqual(scheduled[0].delay,5)
        self.assertIs(scope['_REFRESH_TIMERS']['CLIENT'],scheduled[0])
        self.assertTrue(scheduled[0].started)
        newer=object();scope['_REFRESH_TIMERS']['CLIENT']=newer
        scope['_refresh_worker']('CLIENT')
        self.assertIs(scope['_REFRESH_TIMERS']['CLIENT'],newer)
        self.assertEqual(len(scheduled),1)

if __name__ == '__main__': unittest.main()
