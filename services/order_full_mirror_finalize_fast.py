"""Fast finalization for chunked ORDER full mirrors on Render.

The normal chunk transport already does all expensive table creation, index creation and
row insertion in short requests.  Finalize should therefore do only the work that must be
atomic: verify staging row counts, swap tables, and publish mirror state.

Old visible tables are renamed to deterministic ``__old_*`` backups during the atomic
swap.  They are intentionally NOT dropped inside the finalize HTTP request.  Dropping
many TiDB tables after a successful swap can keep the Render worker busy long enough for
the proxy/worker to close the request and return an empty 502 even though the important
swap has already completed.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

from flask import jsonify, request

from blueprints.b2_test_bp import b2_test_bp, _order_cloud_auth_source
from services.order_tidb_connection import get_order_tidb_connection
from services.order_full_mirror_chunk_service import _hash, _manifest, _stale_result
from services.order_full_mirror_service import _STATE_TABLE, _ensure_state_table, _qi, _safe_stage_name


def _request_json_body():
    if str(request.headers.get('Content-Encoding') or '').strip().lower() == 'gzip':
        raw = request.get_data(cache=False)
        try:
            return json.loads(gzip.decompress(raw).decode('utf-8'))
        except Exception as exc:
            raise ValueError(f'invalid gzip JSON payload: {exc}') from exc
    return request.get_json(silent=True) or {}


def _fast_finalize(manifest, snapshot_hash, source_watermark=None, source_site=None, force=False):
    snapshot_hash = _hash(snapshot_hash)
    normalized, total_rows = _manifest(manifest)
    source_watermark = str(source_watermark or '').strip() or None
    source_site = str(source_site or '').strip().upper()[:32] or None

    early = _stale_result(snapshot_hash, source_watermark, bool(force))
    if early is not None:
        return early

    token = snapshot_hash[:8]
    conn = get_order_tidb_connection()
    backups = []
    try:
        _ensure_state_table(conn)
        cur = conn.cursor()

        # Staging rows were uploaded in bounded chunk requests.  Finalize still verifies
        # exact counts before any visible table can be replaced.
        for table in normalized:
            stage = _safe_stage_name('__stg', table['name'], token)
            cur.execute(f'SELECT COUNT(*) AS n FROM {_qi(stage)}')
            row = cur.fetchone() or {}
            actual = int(row.get('n') or 0)
            expected = int(table.get('expected_rows') or 0)
            if actual != expected:
                raise ValueError(
                    f'incomplete staging table {table["name"]}: expected {expected}, got {actual}'
                )

        cur.execute('SHOW TABLES')
        existing = set()
        for row in cur.fetchall() or []:
            value = next(iter(row.values()), None) if isinstance(row, dict) else (row[0] if row else None)
            if value:
                existing.add(str(value))

        incoming = {t['name'] for t in normalized}
        visible_existing = {
            name for name in existing
            if name != _STATE_TABLE and not name.startswith('__stg_') and not name.startswith('__old_')
        }

        rename_parts = []
        for name in sorted(incoming):
            stage = _safe_stage_name('__stg', name, token)
            if name in visible_existing:
                backup = _safe_stage_name('__old', name, token)
                # Only a retry of the SAME snapshot can already have this exact backup
                # target.  Avoid issuing dozens of unconditional DROP TABLE statements.
                if backup in existing:
                    cur.execute(f'DROP TABLE {_qi(backup)}')
                    existing.discard(backup)
                rename_parts.append(f'{_qi(name)} TO {_qi(backup)}')
                backups.append(backup)
            rename_parts.append(f'{_qi(stage)} TO {_qi(name)}')

        for name in sorted(visible_existing - incoming):
            backup = _safe_stage_name('__old', name, token)
            if backup in existing:
                cur.execute(f'DROP TABLE {_qi(backup)}')
                existing.discard(backup)
            rename_parts.append(f'{_qi(name)} TO {_qi(backup)}')
            backups.append(backup)

        # TiDB/MySQL RENAME TABLE is atomic for this multi-table rename.  This is the
        # only operation in finalize that needs to move all visible tables together.
        if rename_parts:
            cur.execute('RENAME TABLE ' + ', '.join(rename_parts))
        conn.commit()

        committed_at = datetime.now(timezone.utc).isoformat()
        cur.execute(f'SELECT id FROM {_qi(_STATE_TABLE)} WHERE id=1')
        if cur.fetchone():
            cur.execute(
                f"""UPDATE {_qi(_STATE_TABLE)}
                    SET snapshot_hash=%s, source_watermark=%s, source_site=%s,
                        table_count=%s, row_count=%s, committed_at=%s WHERE id=1""",
                (snapshot_hash, source_watermark, source_site, len(normalized), total_rows, committed_at),
            )
        else:
            cur.execute(
                f"""INSERT INTO {_qi(_STATE_TABLE)}
                    (id, snapshot_hash, source_watermark, source_site, table_count, row_count, committed_at)
                    VALUES (1,%s,%s,%s,%s,%s,%s)""",
                (snapshot_hash, source_watermark, source_site, len(normalized), total_rows, committed_at),
            )
        conn.commit()

        # IMPORTANT: no DROP TABLE loop here.  Old backups are harmless because all
        # ORDER readers explicitly ignore __old_* tables.  Cleanup can be performed in
        # separate bounded requests without holding this user-facing finalize request.
        return {
            'changed': True,
            'snapshot_hash': snapshot_hash,
            'tables': len(normalized),
            'rows': total_rows,
            'source_watermark': source_watermark,
            'committed_at': committed_at,
            'deferred_backup_tables': len(backups),
            'finalize_mode': 'fast_atomic_swap',
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


@b2_test_bp.before_app_request
def _fast_full_mirror_finalize_interceptor():
    """Intercept only the expensive full-mirror finalize endpoint."""
    if request.method != 'POST' or request.path != '/api/order-cloud/sync/full-mirror/finalize':
        return None

    source_site, auth_error = _order_cloud_auth_source()
    if auth_error:
        return auth_error
    try:
        payload = _request_json_body()
        result = _fast_finalize(
            payload.get('manifest') or [],
            payload.get('snapshot_hash'),
            source_watermark=payload.get('source_watermark'),
            source_site=source_site,
            force=bool(payload.get('force', False)),
        )
        return jsonify({'ok': True, 'result': result})
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}), 500
