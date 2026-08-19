"""Optional local ORDER startup hook for safe text-only cloud sync.

This module does nothing unless ORDER_CLOUD_AUTOSYNC_ENABLED=1 is set on that
computer. It never runs on Render/cloud mode and never uploads images/PDFs.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading

_started = False
_lock = threading.Lock()


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _find_sync_script() -> Path | None:
    explicit = (os.environ.get("ORDER_CLOUD_SYNC_SCRIPT") or "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return p.resolve()

    order_dir = Path(__file__).resolve().parent
    parent = order_dir.parent
    candidates = [
        parent / "Render-Flask" / "scripts" / "order_cloud_sync_all.py",
        parent / "Render-Flask" / "scripts" / "order_cloud_sync_all.py",
        Path.cwd() / "Render-Flask" / "scripts" / "order_cloud_sync_all.py",
        Path.cwd() / "scripts" / "order_cloud_sync_all.py",
    ]
    seen = set()
    for candidate in candidates:
        try:
            p = candidate.resolve()
        except Exception:
            continue
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            return p
    return None


def _run_sync(script: Path) -> None:
    try:
        env = os.environ.copy()
        cmd = [
            sys.executable,
            str(script),
            "--quiet",
            "--min-interval-minutes",
            str(max(0, int(env.get("ORDER_CLOUD_AUTOSYNC_MIN_MINUTES", "30")))),
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            cmd,
            cwd=str(script.parent.parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=creationflags,
        )
        if result.returncode not in (0,):
            print(f"[ORDER Cloud Sync] background sync exited with code {result.returncode}")
    except Exception as exc:
        # Cloud failure must never break local ORDER startup/business work.
        print(f"[ORDER Cloud Sync] skipped/failed without affecting local ORDER: {type(exc).__name__}: {exc}")


def start_background_order_cloud_sync(app=None) -> bool:
    """Start at most one non-blocking sync worker in this process."""
    global _started

    if not _env_true("ORDER_CLOUD_AUTOSYNC_ENABLED", False):
        return False
    if not (os.environ.get("ORDER_SYNC_API_KEY") or "").strip():
        print("[ORDER Cloud Sync] ORDER_SYNC_API_KEY is not configured; local ORDER continues normally")
        return False

    # Flask debug reloader creates a parent + child process. Only the serving child
    # should launch the sync worker.
    if app is not None and bool(getattr(app, "debug", False)):
        marker = str(os.environ.get("WERKZEUG_RUN_MAIN") or "").lower()
        if marker not in {"true", "1"}:
            return False

    script = _find_sync_script()
    if script is None:
        print("[ORDER Cloud Sync] sync script not found; local ORDER continues normally")
        return False

    with _lock:
        if _started:
            return False
        _started = True
        thread = threading.Thread(
            target=_run_sync,
            args=(script,),
            name="order-cloud-data-sync",
            daemon=True,
        )
        thread.start()
    return True
