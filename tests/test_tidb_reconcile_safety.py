"""Regression checks: an out-of-date TiDB must not delete another TiDB's rows."""
import ast
import pathlib
import unittest


SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'services' / 'order_tidb_cloud_reconcile.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
names = {'_qi', '_table_exists', '_upsert_table', '_standby_only_counts',
         '_invalidate_derived_views'}
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
scope = {'_IDENT': __import__('re').compile(r'^[A-Za-z_][A-Za-z0-9_]*$'),
         '_TABLES': ('cloud_assets',), '_PRIMARY_KEYS': {'cloud_assets': 'asset_key'},
         '_STATE_TABLE': 'cloud_tidb_mirror_state',
         '_ensure_destination_schema': lambda *args: None}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), scope)


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self.rows = []

    def execute(self, sql, params=None):
        self.conn.commands.append(sql)
        if sql.startswith('SHOW TABLES'):
            self.rows = [{'table': params[0]}]
        elif sql.startswith('SELECT *'):
            self.rows = list(self.conn.rows)
        elif sql.startswith('SELECT `asset_key`'):
            self.rows = [{'asset_key': row['asset_key']} for row in self.conn.rows]

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def fetchmany(self, limit):
        rows, self.rows = self.rows[:limit], self.rows[limit:]
        return rows

    def executemany(self, sql, values):
        self.conn.commands.append(sql)
        self.rowcount = len(values)


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.commands = []

    def cursor(self):
        return Cursor(self)

    def commit(self):
        pass


class ReconcileSafetyTests(unittest.TestCase):
    def test_empty_primary_preserves_standby_only_image(self):
        source = Connection([])
        standby = Connection([{'asset_key': 'image-only-on-standby'}])
        counts = scope['_standby_only_counts'](source, standby)
        result = scope['_upsert_table'](source, standby, 'cloud_assets')
        self.assertEqual(counts, {'cloud_assets': 1})
        self.assertEqual(result['rows'], 0)
        self.assertFalse(any('DELETE' in sql for sql in standby.commands))

    def test_existing_source_rows_are_upserted_without_deleting_other_keys(self):
        source = Connection([{'asset_key': 'image-a', 'active': 1}])
        standby = Connection([{'asset_key': 'image-b', 'active': 1}])
        result = scope['_upsert_table'](source, standby, 'cloud_assets')
        self.assertEqual(result['rows'], 1)
        self.assertTrue(any('ON DUPLICATE KEY UPDATE' in sql for sql in standby.commands))
        self.assertFalse(any('DELETE' in sql for sql in standby.commands))

    def test_derived_views_are_cleared_after_metadata_changes(self):
        standby = Connection([])
        scope['_invalidate_derived_views'](standby)
        deletes = [sql for sql in standby.commands if sql.startswith('DELETE')]
        self.assertEqual(deletes, ['DELETE FROM `cloud_customer_share_snapshot`',
                                   'DELETE FROM `cloud_customer_share_html_cache`'])


if __name__ == '__main__':
    unittest.main()
