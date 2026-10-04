"""B2 metadata listing does not block ORDER snapshot construction."""
import ast
from pathlib import Path
import threading
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'services' / 'order_share_thumb_metadata_patch.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
functions = {'_load_build_rows', '_b2_recovery_worker', '_asset_insert_sql'}
module = ast.Module(
    body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
          *(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in functions)],
    type_ignores=[],
)
ast.fix_missing_locations(module)


class Cursor:
    def execute(self, *_args):
        pass

    def fetchall(self):
        return []


class Connection:
    def close(self):
        pass


class EndWorker(Exception):
    pass


class OneItemQueue:
    def __init__(self):
        self.count = 0

    def get(self):
        self.count += 1
        if self.count > 1:
            raise EndWorker()
        return 'SERGIO CONDO COLQUE'

    def task_done(self):
        pass


class AsyncRecoveryTests(unittest.TestCase):
    def test_recovery_uses_the_configured_database_dialect(self):
        scope = {}
        exec(compile(module, str(SOURCE), 'exec'), scope)
        # DATABASE_TYPE lives on config.config, as used by database.py; the
        # module itself deliberately has no DATABASE_TYPE attribute.
        for dialect, expected in (
            ('tidb', 'INSERT IGNORE INTO'),
            ('mysql', 'INSERT IGNORE INTO'),
            ('sqlite', 'INSERT OR IGNORE INTO'),
            ('postgresql', 'ON CONFLICT (asset_key) DO NOTHING'),
        ):
            with self.subTest(dialect=dialect):
                config_module = types.ModuleType('config')
                config_module.config = types.SimpleNamespace(DATABASE_TYPE=dialect)
                with patch.dict(sys.modules, {'config': config_module}):
                    sql = scope['_asset_insert_sql']()
                self.assertIn(expected, sql)
                if dialect in ('mysql', 'tidb'):
                    self.assertNotIn('OR IGNORE', sql)

    def test_snapshot_reads_tidb_without_waiting_for_b2_listing(self):
        scheduled = []
        scope = {
            '_queue_customer_asset_recovery': scheduled.append,
            '_safe_recover_customer_assets': lambda _key: self.fail('synchronous B2 listing'),
            'get_db_connection': Connection, 'get_cursor': lambda _conn: Cursor(),
            'get_row_dict': lambda row, _cur: row,
        }
        exec(compile(module, str(SOURCE), 'exec'), scope)
        self.assertEqual(scope['_load_build_rows']('SERGIO CONDO COLQUE'), ([], []))
        self.assertEqual(scheduled, ['SERGIO CONDO COLQUE'])

    def test_new_metadata_queues_snapshot_refresh(self):
        calls = []
        cache = type('Snapshot', (), {'queue_snapshot_refresh': staticmethod(
            lambda customer, delay: calls.append((customer, delay))
        )})
        pending = {'SERGIO CONDO COLQUE'}
        scope = {
            '_B2_RECOVERY_QUEUE': OneItemQueue(),
            '_B2_RECOVERY_SCHEDULE_LOCK': threading.Lock(),
            '_B2_RECOVERY_PENDING': pending,
            '_safe_recover_customer_assets': lambda _key: 2,
            '_snapshot': cache,
        }
        exec(compile(module, str(SOURCE), 'exec'), scope)
        with self.assertRaises(EndWorker):
            scope['_b2_recovery_worker']()
        self.assertEqual(calls, [('SERGIO CONDO COLQUE', 0.05)])
        self.assertEqual(pending, set())


if __name__ == '__main__':
    unittest.main()
