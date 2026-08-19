"""Safe SQLite snapshot support for the order tracking database.

Snapshots are created with sqlite3.Connection.backup(), validated, then atomically
renamed into place. This keeps sync software from seeing a half-written .db file.
"""
from __future__ import annotations

import atexit
import hashlib
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import (
    DATABASE_PATH,
    SNAPSHOT_DIR,
    SNAPSHOT_ENABLED,
    SNAPSHOT_RETENTION_COUNT,
    SNAPSHOT_RETENTION_DAYS,
    SNAPSHOT_SCHEDULE_HOURS,
    SNAPSHOT_START_DELAY_SECONDS,
    NOTIFICATION_CLEANUP_ENABLED,
    NOTIFICATION_CLEANUP_HOUR,
    NOTIFICATION_CLEANUP_MINUTE,
    STARTUP_VACUUM_ONCE_ENABLED,
)

_scheduler = None
_scheduler_lock = threading.Lock()
_start_timer = None
_start_timer_lock = threading.Lock()
_atexit_registered = False


def _log(message: str) -> None:
    print(f"[Snapshot] {message}")


def _snapshot_lock_path(database_path: str) -> str:
    """Put the inter-process lock outside the synchronized data directory."""
    digest = hashlib.sha1(os.path.abspath(database_path).encode("utf-8", "ignore")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"order_tracking_snapshot_{digest}.lock")


def _acquire_process_lock(database_path: str, stale_seconds: int = 7200) -> Optional[str]:
    lock_path = _snapshot_lock_path(database_path)
    try:
        if os.path.exists(lock_path):
            try:
                age = time.time() - os.path.getmtime(lock_path)
                if age > stale_seconds:
                    os.remove(lock_path)
            except OSError:
                pass

        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"pid={os.getpid()}\ntime={datetime.now().isoformat()}\n".encode("utf-8"))
        finally:
            os.close(fd)
        return lock_path
    except FileExistsError:
        return None


def _release_process_lock(lock_path: Optional[str]) -> None:
    if not lock_path:
        return
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        _log(f"warning: could not remove lock file: {exc}")


def _validate_snapshot(snapshot_path: str) -> None:
    if not os.path.exists(snapshot_path) or os.path.getsize(snapshot_path) <= 0:
        raise RuntimeError("snapshot file is empty")

    conn = sqlite3.connect(snapshot_path, timeout=30)
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        messages = [str(row[0]).strip().lower() for row in rows]
        if not messages or any(message != "ok" for message in messages):
            raise RuntimeError("integrity_check failed: " + "; ".join(messages[:10]))
    finally:
        conn.close()


def _cleanup_old_snapshots(snapshot_dir: str, now: Optional[datetime] = None) -> int:
    now = now or datetime.now()
    folder = Path(snapshot_dir)
    files = []
    for path in folder.glob("tracking_backup_*.db"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue

    files.sort(key=lambda item: item[0], reverse=True)
    cutoff = now - timedelta(days=max(1, int(SNAPSHOT_RETENTION_DAYS)))
    removed = 0

    for index, (mtime, path) in enumerate(files):
        too_many = index >= max(1, int(SNAPSHOT_RETENTION_COUNT))
        too_old = datetime.fromtimestamp(mtime) < cutoff
        if not (too_many or too_old):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            _log(f"warning: could not delete old snapshot {path.name}: {exc}")
    return removed


def create_tracking_snapshot(
    database_path: Optional[str] = None,
    snapshot_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Create one validated, atomic SQLite snapshot.

    Returns the final snapshot path, or None when another process is already
    creating a snapshot at the same time.
    """
    database_path = os.path.abspath(database_path or DATABASE_PATH)
    snapshot_dir = os.path.abspath(snapshot_dir or SNAPSHOT_DIR)
    now = now or datetime.now()

    if not os.path.isfile(database_path):
        raise FileNotFoundError(f"database not found: {database_path}")

    os.makedirs(snapshot_dir, exist_ok=True)
    lock_path = _acquire_process_lock(database_path)
    if lock_path is None:
        _log("another process is already creating a snapshot; skipped")
        return None

    stamp = now.strftime("%Y%m%d_%H%M%S")
    final_path = os.path.join(snapshot_dir, f"tracking_backup_{stamp}.db")
    temp_path = os.path.join(
        snapshot_dir,
        f".tracking_backup_{stamp}.{os.getpid()}.{threading.get_ident()}.tmp",
    )

    source = None
    target = None
    try:
        _log(f"starting backup: {database_path}")
        source = sqlite3.connect(database_path, timeout=60)
        source.execute("PRAGMA query_only = ON")
        target = sqlite3.connect(temp_path, timeout=60)

        # SQLite's online backup API produces a transactionally consistent copy,
        # including when the live database is being written by other connections.
        source.backup(target, pages=256, sleep=0.05)
        target.commit()
        target.close()
        target = None
        source.close()
        source = None

        _validate_snapshot(temp_path)
        os.replace(temp_path, final_path)
        removed = _cleanup_old_snapshots(snapshot_dir, now=now)

        size_mb = os.path.getsize(final_path) / (1024 * 1024)
        suffix = f"; removed {removed} old snapshot(s)" if removed else ""
        _log(f"completed: {os.path.basename(final_path)} ({size_mb:.2f} MB), integrity_check=ok{suffix}")
        return final_path
    except Exception as exc:
        _log(f"FAILED: {exc}")
        raise
    finally:
        if target is not None:
            try:
                target.close()
            except Exception:
                pass
        if source is not None:
            try:
                source.close()
            except Exception:
                pass
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        _release_process_lock(lock_path)


def _scheduled_snapshot_job() -> None:
    try:
        create_tracking_snapshot()
    except FileNotFoundError as exc:
        _log(f"scheduled backup skipped: {exc}")
    except Exception as exc:
        _log(f"scheduled backup failed: {exc}")


def _scheduled_notification_cleanup_job() -> None:
    if not NOTIFICATION_CLEANUP_ENABLED:
        return
    try:
        from .maintenance import cleanup_old_notifications
        cleanup_old_notifications()
    except FileNotFoundError as exc:
        print(f"[Maintenance] notification cleanup skipped: {exc}")
    except Exception as exc:
        print(f"[Maintenance] notification cleanup failed: {exc}")


def _startup_cleanup_and_vacuum_once_job() -> None:
    if not STARTUP_VACUUM_ONCE_ENABLED:
        return
    try:
        from .maintenance import run_startup_cleanup_and_vacuum_once
        run_startup_cleanup_and_vacuum_once()
    except FileNotFoundError as exc:
        print(f"[Maintenance] startup VACUUM skipped: {exc}")
    except Exception as exc:
        print(f"[Maintenance] startup VACUUM failed: {exc}")


def _shutdown_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        scheduler = _scheduler
        _scheduler = None
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass


def start_snapshot_scheduler():
    """Start one APScheduler instance in this Python process."""
    global _scheduler, _atexit_registered

    if not SNAPSHOT_ENABLED:
        _log("scheduler disabled by configuration")
        return None

    with _scheduler_lock:
        if _scheduler is not None and getattr(_scheduler, "running", False):
            return _scheduler

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError as exc:
            _log("APScheduler is not installed; automatic snapshots are disabled")
            raise RuntimeError("APScheduler is required for automatic snapshots") from exc

        hours = sorted({int(hour) for hour in SNAPSHOT_SCHEDULE_HOURS if 0 <= int(hour) <= 23})
        if not hours:
            raise ValueError("SNAPSHOT_SCHEDULE_HOURS must contain at least one hour from 0 to 23")

        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            _scheduled_snapshot_job,
            trigger="cron",
            hour=",".join(str(hour) for hour in hours),
            minute=0,
            second=0,
            id="order_tracking_sqlite_snapshot",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=1800,
        )
        if NOTIFICATION_CLEANUP_ENABLED:
            scheduler.add_job(
                _scheduled_notification_cleanup_job,
                trigger="cron",
                hour=int(NOTIFICATION_CLEANUP_HOUR),
                minute=int(NOTIFICATION_CLEANUP_MINUTE),
                second=0,
                id="order_tracking_notification_cleanup",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )
        if STARTUP_VACUUM_ONCE_ENABLED:
            scheduler.add_job(
                _startup_cleanup_and_vacuum_once_job,
                trigger="date",
                run_date=datetime.now() + timedelta(seconds=1),
                id="order_tracking_startup_vacuum_once",
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=600,
            )
        scheduler.start()
        _scheduler = scheduler

        if not _atexit_registered:
            atexit.register(_shutdown_scheduler)
            _atexit_registered = True

        schedule_text = ", ".join(f"{hour:02d}:00" for hour in hours)
        _log(f"scheduler started; daily at {schedule_text} (server local time)")
        _log(f"snapshot directory: {SNAPSHOT_DIR}")
        if NOTIFICATION_CLEANUP_ENABLED:
            print(
                f"[Maintenance] notification cleanup scheduled daily at "
                f"{int(NOTIFICATION_CLEANUP_HOUR):02d}:{int(NOTIFICATION_CLEANUP_MINUTE):02d}"
            )
        return scheduler


def schedule_snapshot_scheduler_start(delay_seconds: Optional[float] = None) -> None:
    """Start the scheduler shortly after Blueprint registration.

    The small daemon delay avoids doing work during module import and greatly
    reduces duplicate starts in Werkzeug's debug reloader parent process. Even
    if multiple worker processes start schedulers, the snapshot job itself is
    protected by an inter-process lock so only one backup runs at a time.
    """
    global _start_timer

    if not SNAPSHOT_ENABLED:
        return

    with _start_timer_lock:
        if (_scheduler is not None and getattr(_scheduler, "running", False)) or (
            _start_timer is not None and _start_timer.is_alive()
        ):
            return

        delay = SNAPSHOT_START_DELAY_SECONDS if delay_seconds is None else delay_seconds

        def _start():
            try:
                start_snapshot_scheduler()
            except Exception as exc:
                _log(f"scheduler start failed: {exc}")

        _start_timer = threading.Timer(max(0.0, float(delay)), _start)
        _start_timer.daemon = True
        _start_timer.start()


if __name__ == "__main__":
    path = create_tracking_snapshot()
    if path:
        print(path)
