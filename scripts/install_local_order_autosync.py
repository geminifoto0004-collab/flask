#!/usr/bin/env python3
"""Install the safe ORDER startup cloud-sync hook into the sibling local source.

The installer changes Python source only. It never opens/writes tracking.db and never
touches uploads. The actual sync is background/read-only and is opt-in per computer
through ORDER_CLOUD_AUTOSYNC_ENABLED=1.
"""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import py_compile
import shutil
import sys

MARKER = "def _register_cloud_data_autosync(state):"
HOOK = '''@tracking_bp.record_once
def _register_cloud_data_autosync(state):
    """Optional local-only ORDER -> Render/TiDB text sync; never runs in cloud mode."""
    app = state.app
    if bool(app.config.get('TRACKING_CLOUD_MODE', CLOUD_MODE)):
        return
    try:
        from .cloud_data_autosync import start_background_order_cloud_sync
        start_background_order_cloud_sync(app)
    except Exception as exc:
        # Cloud sync must never prevent the local ORDER blueprint from registering.
        print(f'[ORDER Cloud Sync] startup hook failed safely: {type(exc).__name__}: {exc}')


'''
ANCHOR = "@tracking_bp.record_once\ndef _register_snapshot_scheduler(state):"


def _discover_local(repo: Path, explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    configured = (os.environ.get("ORDER_TRACKING_SOURCE_DIR") or "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.extend([
        repo.parent / "order_tracking",
        repo.parent.parent / "order_tracking",
        Path.cwd().parent / "order_tracking",
    ])
    repo_copy = (repo / "order_tracking").resolve()
    seen = set()
    for candidate in candidates:
        try:
            p = candidate.expanduser().resolve()
        except Exception:
            continue
        if p in seen or p == repo_copy:
            continue
        seen.add(p)
        if (p / "__init__.py").is_file() and (p / "config.py").is_file():
            return p
    raise SystemExit("Local sibling order_tracking source not found")


def _patch_init(path: Path) -> bool:
    text = path.read_text("utf-8")
    if MARKER in text:
        return False
    if ANCHOR not in text:
        raise RuntimeError("ORDER __init__.py startup anchor changed; refusing unsafe automatic patch")
    text = text.replace(ANCHOR, HOOK + ANCHOR, 1)
    path.write_text(text, "utf-8")
    return True


def _broadcast_windows_environment_change() -> None:
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            3000,
            ctypes.byref(result),
        )
    except Exception:
        pass


def _persist_windows_env(name: str, value: str) -> None:
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    os.environ[name] = value


def _configure_machine(persist_key: bool) -> None:
    if os.name != "nt":
        print("Non-Windows: set ORDER_CLOUD_AUTOSYNC_ENABLED=1 in the user's login environment")
        return
    _persist_windows_env("ORDER_CLOUD_AUTOSYNC_ENABLED", "1")
    if persist_key:
        current = (os.environ.get("ORDER_SYNC_API_KEY") or "").strip()
        if not current:
            raise RuntimeError(
                "--persist-key requested but ORDER_SYNC_API_KEY is not present in this CMD session"
            )
        # Never print the secret.
        _persist_windows_env("ORDER_SYNC_API_KEY", current)
    _broadcast_windows_environment_change()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="explicit local order_tracking folder")
    ap.add_argument(
        "--persist-key",
        action="store_true",
        help="persist the current ORDER_SYNC_API_KEY in the Windows user environment without printing it",
    )
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[1]
    local_order = _discover_local(repo, args.source)
    source_module = repo / "order_tracking" / "cloud_data_autosync.py"
    if not source_module.is_file():
        raise SystemExit(f"missing installer module: {source_module}")

    init_py = local_order / "__init__.py"
    dest_module = local_order / "cloud_data_autosync.py"

    print(f"Local ORDER source: {local_order}")
    print("tracking.db/uploads: NOT TOUCHED")

    shutil.copy2(source_module, dest_module)
    changed = _patch_init(init_py)

    py_compile.compile(str(dest_module), doraise=True)
    py_compile.compile(str(init_py), doraise=True)
    shutil.rmtree(local_order / "__pycache__", ignore_errors=True)

    _configure_machine(bool(args.persist_key))

    print("ORDER startup cloud sync installed")
    print(f"Hook added: {'YES' if changed else 'already present'}")
    print(f"Key persisted: {'YES' if args.persist_key else 'NO'}")
    print("Future local Flask/ORDER starts will launch a background text-only incremental sync")
    print("Images/PDF/Access are never uploaded by this startup hook")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
