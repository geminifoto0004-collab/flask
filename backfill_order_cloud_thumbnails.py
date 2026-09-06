#!/usr/bin/env python3
"""Offline/re-runnable thumbnail backfill for ORDER cloud_assets.

Run from the Render service repo root (or any machine with the same TiDB/B2 env vars):
  python backfill_order_cloud_thumbnails.py --sleep 0.20
  python backfill_order_cloud_thumbnails.py --dry-run --limit 100

The script never runs in a web request. It HEADs the deterministic thumbnail key,
creates only missing 480px JPEGs, and updates the existing cloud_assets row.
"""
import argparse
import hashlib
import time

from botocore.exceptions import ClientError

from database import get_cursor, get_db_connection, get_row_dict
from services.order_cloud_asset_service import init_order_cloud_asset_table
from services.order_cloud_multi_b2 import PRIMARY, client_for_backend, config_for_backend
from services.order_cloud_thumbnail import make_thumb_bytes, thumb_object_key


def _is_missing(exc):
    if not isinstance(exc, ClientError):
        return False
    status = (exc.response.get('ResponseMetadata') or {}).get('HTTPStatusCode')
    code = str((exc.response.get('Error') or {}).get('Code') or '')
    return status == 404 or code in {'404', 'NoSuchKey', 'NotFound'}


def _rows(customer_key='', order_number='', start_after='', limit=0):
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        sql = """SELECT asset_key, customer_key, order_number, workflow_key, sha256,
                        object_key, content_type, file_size, storage_backend,
                        thumb_object_key, thumb_sha256, thumb_content_type, thumb_file_size
                 FROM cloud_assets WHERE active=TRUE AND asset_type='IMAGE'"""
        args = []
        if customer_key:
            sql += ' AND customer_key=?'; args.append(customer_key)
        if order_number:
            sql += ' AND order_number=?'; args.append(order_number)
        if start_after:
            sql += ' AND asset_key>?'; args.append(start_after)
        sql += ' ORDER BY asset_key'
        if limit:
            sql += ' LIMIT ?'; args.append(int(limit))
        cur.execute(sql, tuple(args))
        return [get_row_dict(row, cur) for row in cur.fetchall()]
    finally:
        conn.close()


def _update_metadata(asset_key, key, thumb_sha, size):
    conn = get_db_connection(); cur = get_cursor(conn)
    try:
        cur.execute(
            """UPDATE cloud_assets
               SET thumb_object_key=?, thumb_sha256=?, thumb_content_type='image/jpeg',
                   thumb_file_size=?, updated_at=CURRENT_TIMESTAMP
               WHERE asset_key=?""",
            (key, thumb_sha, int(size), asset_key),
        )
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sleep', type=float, default=0.20, help='seconds between assets (default 0.20)')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--customer-key', default='')
    ap.add_argument('--order-number', default='')
    ap.add_argument('--start-after', default='', help='resume after this asset_key')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    init_order_cloud_asset_table()
    rows = _rows(args.customer_key, args.order_number, args.start_after, args.limit)
    stats = {'total': len(rows), 'exists': 0, 'created': 0, 'metadata_fixed': 0, 'failed': 0}
    print(f"[thumb-backfill] rows={len(rows)} dry_run={args.dry_run} sleep={args.sleep}s")

    for n, asset in enumerate(rows, 1):
        key = thumb_object_key(asset.get('sha256'))
        backend = str(asset.get('storage_backend') or PRIMARY).strip().lower()
        try:
            cfg = config_for_backend(backend, required=True)
            s3 = client_for_backend(backend)
            head = None
            try:
                head = s3.head_object(Bucket=cfg['bucket_name'], Key=key)
            except ClientError as exc:
                if not _is_missing(exc):
                    raise

            if head is not None:
                stats['exists'] += 1
                size = int(head.get('ContentLength') or asset.get('thumb_file_size') or 0)
                # We cannot recover the thumb byte SHA from HEAD. Preserve existing SHA;
                # if missing, use a sentinel NULL while still recording the deterministic key.
                if not args.dry_run and not asset.get('thumb_object_key'):
                    conn = get_db_connection(); cur = get_cursor(conn)
                    try:
                        cur.execute(
                            """UPDATE cloud_assets SET thumb_object_key=?, thumb_content_type='image/jpeg',
                                      thumb_file_size=?, updated_at=CURRENT_TIMESTAMP WHERE asset_key=?""",
                            (key, size or None, asset['asset_key']),
                        ); conn.commit()
                    except Exception:
                        conn.rollback(); raise
                    finally:
                        conn.close()
                    stats['metadata_fixed'] += 1
                print(f"[{n}/{len(rows)}] EXISTS {asset['asset_key'][:10]} {key}")
            else:
                if args.dry_run:
                    print(f"[{n}/{len(rows)}] MISSING {asset['asset_key'][:10]} would create {key}")
                else:
                    obj = s3.get_object(Bucket=cfg['bucket_name'], Key=asset['object_key'])
                    original = obj['Body'].read()
                    thumb_data, size_px, thumb_sha = make_thumb_bytes(original)
                    s3.put_object(Bucket=cfg['bucket_name'], Key=key, Body=thumb_data, ContentType='image/jpeg')
                    _update_metadata(asset['asset_key'], key, thumb_sha, len(thumb_data))
                    stats['created'] += 1
                    print(f"[{n}/{len(rows)}] CREATED {asset['asset_key'][:10]} {size_px[0]}x{size_px[1]} {len(thumb_data)}B")
        except Exception as exc:
            stats['failed'] += 1
            print(f"[{n}/{len(rows)}] FAILED {asset.get('asset_key')} {type(exc).__name__}: {exc}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    print('[thumb-backfill] ' + ' '.join(f'{k}={v}' for k, v in stats.items()))
    if rows:
        print('[thumb-backfill] last_asset_key=' + str(rows[-1].get('asset_key') or ''))


if __name__ == '__main__':
    main()
