"""Background maintenance jobs for order_tracking.

Currently handles automatic notification retention cleanup. The cleanup is safe
for a live SQLite database: it deletes old rows in small committed batches and
can also run a guarded one-time startup VACUUM when explicitly enabled.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import time
from datetime import datetime
from typing import Optional

from .config import (
    DATABASE_PATH,
    NOTIFICATION_CLEANUP_BATCH_SIZE,
    STARTUP_VACUUM_ONCE_KEY,
)


def _log(message: str) -> None:
    print(f"[Maintenance] {message}")


def _lock_path(database_path: str) -> str:
    digest = hashlib.sha1(os.path.abspath(database_path).encode("utf-8", "ignore")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"order_tracking_notification_cleanup_{digest}.lock")


def _acquire_lock(database_path: str, stale_seconds: int = 7200) -> Optional[str]:
    path = _lock_path(database_path)
    try:
        if os.path.exists(path):
            try:
                if time.time() - os.path.getmtime(path) > stale_seconds:
                    os.remove(path)
            except OSError:
                pass
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"pid={os.getpid()}\ntime={datetime.now().isoformat()}\n".encode("utf-8"))
        finally:
            os.close(fd)
        return path
    except FileExistsError:
        return None


def _release_lock(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except (FileNotFoundError, OSError):
        pass


def _get_retention_days(conn: sqlite3.Connection, default: int = 30) -> int:
    """Use the existing system setting as both display and retention days."""
    try:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = 'notification_visible_days'"
        ).fetchone()
        if row:
            days = int(row[0])
            if 1 <= days <= 365:
                return days
    except Exception:
        pass
    return default


def cleanup_old_notifications(
    database_path: Optional[str] = None,
    retention_days: Optional[int] = None,
    batch_size: Optional[int] = None,
) -> int:
    """Delete notifications older than the configured retention period.

    Rows are deleted in small batches so the live application is not held by one
    very large write transaction. This intentionally does NOT run VACUUM; freed
    SQLite pages remain reusable by future data and can be compacted manually
    during maintenance if desired.
    """
    database_path = os.path.abspath(database_path or DATABASE_PATH)
    batch_size = max(100, int(batch_size or NOTIFICATION_CLEANUP_BATCH_SIZE))

    if not os.path.isfile(database_path):
        raise FileNotFoundError(f"database not found: {database_path}")

    lock = _acquire_lock(database_path)
    if lock is None:
        _log("another process is already cleaning notifications; skipped")
        return 0

    total_deleted = 0
    conn = None
    try:
        conn = sqlite3.connect(database_path, timeout=60)
        conn.execute("PRAGMA busy_timeout = 60000")

        days = int(retention_days) if retention_days is not None else _get_retention_days(conn, 30)
        days = min(365, max(1, days))
        modifier = f"-{days} days"

        row = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE created_at < datetime('now', ?)",
            (modifier,),
        ).fetchone()
        pending = int(row[0] if row else 0)
        if pending <= 0:
            _log(f"notification cleanup: nothing older than {days} day(s)")
            return 0

        _log(f"notification cleanup started: {pending} row(s) older than {days} day(s)")

        while True:
            cur = conn.execute(
                """
                DELETE FROM notifications
                WHERE id IN (
                    SELECT id
                    FROM notifications
                    WHERE created_at < datetime('now', ?)
                    ORDER BY created_at, id
                    LIMIT ?
                )
                """,
                (modifier, batch_size),
            )
            deleted = max(0, int(cur.rowcount or 0))
            conn.commit()
            total_deleted += deleted
            if deleted < batch_size:
                break
            # Give concurrent requests a chance to obtain the write lock.
            time.sleep(0.03)

        _log(
            f"notification cleanup completed: deleted {total_deleted} row(s); "
            "freed pages are reusable (VACUUM is not run automatically)"
        )
        return total_deleted
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        _release_lock(lock)



def _startup_vacuum_lock_path(database_path: str) -> str:
    digest = hashlib.sha1(os.path.abspath(database_path).encode("utf-8", "ignore")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"order_tracking_startup_vacuum_{digest}.lock")


def _acquire_named_lock(path: str, stale_seconds: int = 7200) -> Optional[str]:
    try:
        if os.path.exists(path):
            try:
                if time.time() - os.path.getmtime(path) > stale_seconds:
                    os.remove(path)
            except OSError:
                pass
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"pid={os.getpid()}\ntime={datetime.now().isoformat()}\n".encode("utf-8"))
        finally:
            os.close(fd)
        return path
    except FileExistsError:
        return None


def _maintenance_marker_is_done(database_path: str, marker_key: str) -> bool:
    conn = sqlite3.connect(database_path, timeout=30)
    try:
        row = conn.execute(
            "SELECT value FROM system_settings WHERE key = ?",
            (marker_key,),
        ).fetchone()
        return bool(row and str(row[0]).strip().lower() == "done")
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def _save_maintenance_marker(database_path: str, marker_key: str) -> None:
    conn = sqlite3.connect(database_path, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout = 60000")
        conn.execute(
            """
            INSERT INTO system_settings (key, value, description, updated_at)
            VALUES (?, 'done', '一次性通知清理与 VACUUM 已完成', CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = 'done',
                description = excluded.description,
                updated_at = CURRENT_TIMESTAMP
            """,
            (marker_key,),
        )
        conn.commit()
    finally:
        conn.close()


def vacuum_database(database_path: Optional[str] = None) -> dict:
    """Compact the SQLite database and return before/after file sizes.

    VACUUM requires an exclusive write window. A generous busy_timeout is used;
    if another request keeps the database busy, this function raises and the
    one-time startup job will simply retry on the next application restart.
    """
    database_path = os.path.abspath(database_path or DATABASE_PATH)
    if not os.path.isfile(database_path):
        raise FileNotFoundError(f"database not found: {database_path}")

    before = os.path.getsize(database_path)
    conn = sqlite3.connect(database_path, timeout=120, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout = 120000")
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            pass
        _log(f"VACUUM started: {before / (1024 * 1024):.2f} MB")
        conn.execute("VACUUM")
    finally:
        conn.close()

    after = os.path.getsize(database_path)
    saved = max(0, before - after)
    _log(
        f"VACUUM completed: {after / (1024 * 1024):.2f} MB; "
        f"reclaimed {saved / (1024 * 1024):.2f} MB"
    )
    return {"before_bytes": before, "after_bytes": after, "saved_bytes": saved}


def run_startup_cleanup_and_vacuum_once(
    database_path: Optional[str] = None,
    marker_key: Optional[str] = None,
    create_safety_snapshot: bool = True,
) -> dict:
    """Run the requested one-time startup maintenance safely.

    Sequence: safety snapshot -> notification retention cleanup -> VACUUM ->
    persistent completion marker. The marker is written only after VACUUM
    succeeds, making the job safe to retry after a lock/error.
    """
    database_path = os.path.abspath(database_path or DATABASE_PATH)
    marker_key = str(marker_key or STARTUP_VACUUM_ONCE_KEY)

    if not os.path.isfile(database_path):
        raise FileNotFoundError(f"database not found: {database_path}")

    lock = _acquire_named_lock(_startup_vacuum_lock_path(database_path), stale_seconds=7200)
    if lock is None:
        _log("one-time startup VACUUM is already running in another process; skipped")
        return {"status": "locked"}

    try:
        if _maintenance_marker_is_done(database_path, marker_key):
            _log("one-time startup VACUUM already completed earlier; skipped")
            return {"status": "already_done"}

        _log("one-time startup maintenance started")

        snapshot_path = None
        if create_safety_snapshot:
            try:
                from .snapshot import create_tracking_snapshot
                snapshot_path = create_tracking_snapshot(database_path=database_path)
                if snapshot_path:
                    _log(f"safety snapshot created: {snapshot_path}")
            except Exception as exc:
                # For a destructive cleanup/compaction pass, do not continue if
                # the pre-maintenance safety snapshot could not be created.
                raise RuntimeError(f"safety snapshot failed; maintenance aborted: {exc}") from exc

        deleted = cleanup_old_notifications(database_path=database_path)
        sizes = vacuum_database(database_path=database_path)
        _save_maintenance_marker(database_path, marker_key)
        _log("one-time startup maintenance finished and completion marker saved")

        return {
            "status": "done",
            "deleted_notifications": deleted,
            "snapshot_path": snapshot_path,
            **sizes,
        }
    finally:
        _release_lock(lock)
