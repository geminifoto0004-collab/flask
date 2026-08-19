"""Publish real ORDER images to Render -> private B2 -> TiDB metadata.

This is a local-side verification/publisher. It reads the real ORDER config.py so
DATABASE_PATH and UPLOAD_FOLDER remain the single source of truth. Original local
filenames are never sent to Render because they may contain private information.

Windows CMD:
    git pull
    python scripts\order_cloud_sync_real_images.py --latest --share

Or publish a known order:
    python scripts\order_cloud_sync_real_images.py 1008230 --share
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import mimetypes
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Optional

import requests

import order_cloud_sync_real_order as order_sync


ALLOWED = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_BYTES = 15 * 1024 * 1024


class ImageSyncError(RuntimeError):
    pass


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _config_candidates() -> List[Path]:
    candidates: List[Path] = []
    explicit = (os.environ.get("ORDER_TRACKING_CONFIG") or "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    here = Path.cwd()
    candidates.extend([
        here.parent / "order_tracking" / "config.py",
        here / "order_tracking" / "config.py",
        here.parent.parent / "order_tracking" / "config.py",
    ])
    seen = set()
    out = []
    for p in candidates:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _load_order_config():
    for path in _config_candidates():
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("_order_tracking_real_config_images", str(path))
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            db = Path(str(getattr(module, "DATABASE_PATH", "") or ""))
            uploads = Path(str(getattr(module, "UPLOAD_FOLDER", "") or ""))
            if db.is_file() and uploads.exists():
                return path.resolve(), db.resolve(), uploads.resolve()
        except Exception:
            continue
    raise ImageSyncError("Could not load real order_tracking/config.py with DATABASE_PATH and UPLOAD_FOLDER")


def _mime_for_path(path: Path, stored_type: Optional[str] = None) -> Optional[str]:
    value = str(stored_type or "").split(";")[0].strip().lower()
    if value in {"image/jpeg", "image/png", "image/webp"}:
        return value
    ext = path.suffix.lower()
    if ext in ALLOWED:
        return ALLOWED[ext]
    guessed = (mimetypes.guess_type(str(path))[0] or "").lower()
    return guessed if guessed in {"image/jpeg", "image/png", "image/webp"} else None


def _resolve_workflow_file(upload_folder: Path, row: sqlite3.Row) -> Optional[Path]:
    d = dict(row)
    rel = str(d.get("file_path") or "").strip()
    if rel:
        p = upload_folder / Path(rel.replace("/", os.sep))
        if p.is_file():
            return p
        if p.is_dir():
            for key in ("stored_filename", "file_name"):
                name = str(d.get(key) or "").strip()
                if name and (p / name).is_file():
                    return p / name
    workflow = str(d.get("workflow_number") or "").strip()
    for key in ("stored_filename", "file_name"):
        name = str(d.get(key) or "").strip()
        if workflow and name:
            p = upload_folder / "workflows" / workflow / name
            if p.is_file():
                return p
    return None


def _resolve_order_file(upload_folder: Path, row: sqlite3.Row) -> Optional[Path]:
    d = dict(row)
    rel = str(d.get("file_path") or "").strip()
    stored = str(d.get("stored_filename") or d.get("file_name") or "").strip()
    if rel:
        base = upload_folder / Path(rel.replace("/", os.sep))
        if base.is_file():
            return base
        if stored and (base / stored).is_file():
            return base / stored
    order_number = str(d.get("order_number") or "").strip()
    if order_number and stored:
        p = upload_folder / "orders" / order_number / stored
        if p.is_file():
            return p
    return None


def _image_rows(conn: sqlite3.Connection, upload_folder: Path, order_number: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    if _table_exists(conn, "workflow_files") and _table_exists(conn, "workflows"):
        cols = _columns(conn, "workflow_files")
        where_deleted = "AND COALESCE(wf.is_deleted,0)=0" if "is_deleted" in cols else ""
        rows = conn.execute(
            f"""SELECT wf.*, w.order_number
                FROM workflow_files wf
                JOIN workflows w ON w.workflow_number=wf.workflow_number
                WHERE w.order_number=? {where_deleted}
                ORDER BY wf.id ASC""",
            (order_number,),
        ).fetchall()
        for row in rows:
            path = _resolve_workflow_file(upload_folder, row)
            if not path or not path.is_file():
                continue
            d = dict(row)
            mime = _mime_for_path(path, d.get("file_type") or d.get("mime_type"))
            if not mime:
                continue
            items.append({
                "source": "workflow_files",
                "source_id": d.get("id"),
                "workflow_key": str(d.get("workflow_number") or "").strip() or None,
                "path": path,
                "content_type": mime,
            })

    if _table_exists(conn, "order_files"):
        rows = conn.execute("SELECT * FROM order_files WHERE order_number=? ORDER BY id ASC", (order_number,)).fetchall()
        for row in rows:
            path = _resolve_order_file(upload_folder, row)
            if not path or not path.is_file():
                continue
            d = dict(row)
            mime = _mime_for_path(path, d.get("mime_type") or d.get("file_type"))
            if not mime:
                continue
            items.append({
                "source": "order_files",
                "source_id": d.get("id"),
                "workflow_key": None,
                "path": path,
                "content_type": mime,
            })
    return items


def _latest_order_with_image(conn: sqlite3.Connection, upload_folder: Path) -> str:
    order_cols = _columns(conn, "orders")
    order_by = []
    if "order_date" in order_cols:
        order_by.append("order_date DESC")
    if "updated_at" in order_cols:
        order_by.append("updated_at DESC")
    if "created_at" in order_cols:
        order_by.append("created_at DESC")
    order_by.append("order_number DESC")
    rows = conn.execute(f"SELECT order_number FROM orders ORDER BY {', '.join(order_by)} LIMIT 500").fetchall()
    for row in rows:
        number = str(row[0] or "").strip()
        if number and _image_rows(conn, upload_folder, number):
            return number
    raise ImageSyncError("No recent ORDER with a JPEG/PNG/WEBP file was found")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _publish_one(item: Dict[str, Any], order_number: str) -> Dict[str, Any]:
    path: Path = item["path"]
    size = path.stat().st_size
    if size <= 0:
        raise ImageSyncError("empty image")
    if size > MAX_BYTES:
        raise ImageSyncError("image exceeds 15 MB")
    digest = _sha256(path)
    content_type = item["content_type"]
    workflow_key = item.get("workflow_key")

    check = order_sync._request_json("POST", "/api/order-cloud/assets/check", json={"sha256": digest, "content_type": content_type})
    if (check.get("result") or {}).get("exists"):
        result = order_sync._request_json(
            "POST", "/api/order-cloud/assets/register",
            json={"order_number": order_number, "workflow_key": workflow_key, "sha256": digest, "content_type": content_type},
        ).get("result") or {}
        return {"mode": "reused", "result": result}

    with path.open("rb") as f:
        response = requests.post(
            order_sync.BASE_URL + "/api/order-cloud/assets/upload",
            headers=order_sync._headers(),
            data={"order_number": order_number, "workflow_key": workflow_key or "", "sha256": digest},
            files={"file": ("image", f, content_type)},
            timeout=(5, 60),
        )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:500]}
    if not response.ok or not body.get("ok"):
        raise ImageSyncError(f"asset upload failed ({response.status_code}): {body}")
    return {"mode": "uploaded", "result": body.get("result") or {}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish real ORDER images through Render to private B2")
    parser.add_argument("order_number", nargs="?", help="ORDER number")
    parser.add_argument("--latest", action="store_true", help="Use latest recent order that has an eligible image")
    parser.add_argument("--share", action="store_true", help="Create a new 24-hour share URL after publishing")
    args = parser.parse_args()
    if args.order_number and args.latest:
        raise ImageSyncError("Use either an order number or --latest")
    if not args.order_number and not args.latest:
        raise ImageSyncError("Provide an order number or use --latest")

    config_path, db_path, upload_folder = _load_order_config()
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        order_number = _latest_order_with_image(conn, upload_folder) if args.latest else str(args.order_number).strip()
        payload = order_sync._load_order_payload(conn, order_number)
        images = _image_rows(conn, upload_folder, order_number)
    finally:
        conn.close()

    if not images:
        raise ImageSyncError(f"ORDER {order_number} has no eligible local JPEG/PNG/WEBP images")

    print(f"ORDER config: {config_path}")
    print(f"ORDER SQLite: {db_path}")
    print(f"ORDER uploads: {upload_folder}")
    print(f"ORDER: {order_number} | eligible images={len(images)}")
    print("Original filenames: NOT SENT")

    order_sync._request_json("POST", "/api/order-cloud/sync/order", json=payload)
    print("ORDER safe data sync OK")

    uploaded = reused = failed = 0
    for index, item in enumerate(images, 1):
        try:
            out = _publish_one(item, order_number)
            mode = out["mode"]
            if mode == "uploaded":
                uploaded += 1
            else:
                reused += 1
            print(f"IMAGE {index}/{len(images)} OK: {item['source']}#{item.get('source_id')} -> {mode}")
        except Exception as exc:
            failed += 1
            print(f"IMAGE {index}/{len(images)} FAILED: {item['source']}#{item.get('source_id')} -> {exc}")

    print(f"IMAGE SUMMARY: uploaded={uploaded} reused={reused} failed={failed}")
    if failed:
        raise ImageSyncError("one or more images failed to publish")

    if args.share:
        share = order_sync._request_json("POST", "/api/order-cloud/share/create", json={"customer_key": payload["customer_key"], "expires_hours": 24})
        print("SHARE_URL: " + str((share.get("result") or {}).get("share_url") or ""))

    print("REAL ORDER IMAGE CLOUD SYNC PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ImageSyncError, order_sync.SyncError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
