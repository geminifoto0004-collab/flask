#!/usr/bin/env python3
"""Vendor the live sibling ORDER source into this Render repository safely.

The local/sibling ORDER folder is NEVER modified. A clean copy is made into
<repo>/order_tracking, then only that vendored copy receives the Render cloud DB
gateway. This keeps the production local SQLite code/path untouched while still
letting Render follow future ORDER UI/business-code updates.
"""
from __future__ import annotations

import argparse
import os
import py_compile
import shutil
import subprocess
import tempfile
from pathlib import Path

SKIP_DIRS = {
    "__pycache__", ".git", ".idea", ".vscode",
    "data", "uploads", "cache", "sync_snapshot", "snapshots",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".bak"}

DB_BACKEND = r'''"""Database backend switch for shared ORDER code.

Local production remains SQLite unless cloud mode is explicitly enabled.
Render/cloud must register a TiDB-compatible connection factory. Cloud mode
never falls back to a temporary SQLite file, preventing split-brain data.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from flask import current_app, has_app_context

from .config import CLOUD_MODE, DATABASE_PATH

_EXTENSION_KEY = "order_tracking_cloud_db_factory"


def cloud_mode_enabled_for_db() -> bool:
    if has_app_context():
        return bool(current_app.config.get("TRACKING_CLOUD_MODE", CLOUD_MODE))
    return bool(CLOUD_MODE)


def register_cloud_db_connection_factory(app: Any, factory: Callable[[], Any]) -> None:
    if not callable(factory):
        raise TypeError("ORDER cloud DB factory must be callable")
    app.extensions[_EXTENSION_KEY] = factory


def get_registered_cloud_db_factory() -> Callable[[], Any] | None:
    if not has_app_context():
        return None
    factory = current_app.extensions.get(_EXTENSION_KEY)
    return factory if callable(factory) else None


def get_tracking_db_connection():
    # IMPORTANT: this branch is intentionally the exact legacy local behavior.
    if not cloud_mode_enabled_for_db():
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    factory = get_registered_cloud_db_factory()
    if factory is None:
        raise RuntimeError(
            "ORDER cloud database is not registered. "
            "Render must register a TiDB connection factory; local SQLite fallback is disabled."
        )
    conn = factory()
    if conn is None:
        raise RuntimeError("ORDER cloud database factory returned no connection")
    return conn
'''

DOC = """# ORDER SQLite / TiDB dual mode\n\n- Local ORDER remains SQLite and is never modified by the vendor script.\n- The copied Render version uses TiDB only when TRACKING_CLOUD_MODE is enabled.\n- Cloud mode never falls back to Render-local SQLite.\n- Render remains read-only; official business writes stay on local ORDER.\n"""


def ignored(_dir: str, names: list[str]) -> set[str]:
    out = set()
    for name in names:
        if name in SKIP_DIRS or Path(name).suffix.lower() in SKIP_SUFFIXES:
            out.add(name)
    return out


def discover_source(repo: Path, explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("ORDER_TRACKING_SOURCE_DIR", "").strip()
    if env:
        candidates.append(Path(env))
    candidates.extend([
        repo.parent / "order_tracking",
        repo.parent.parent / "order_tracking",
        Path.cwd().parent / "order_tracking",
        Path.cwd() / "order_tracking",
    ])
    seen = set()
    for candidate in candidates:
        try:
            p = candidate.expanduser().resolve()
        except Exception:
            continue
        if p in seen:
            continue
        seen.add(p)
        if (p / "__init__.py").is_file() and (p / "models.py").is_file() and (p / "config.py").is_file():
            return p
    raise SystemExit(
        "ORDER source not found. Set ORDER_TRACKING_SOURCE_DIR to the folder containing "
        "order_tracking/__init__.py, models.py and config.py."
    )


def patch_models(path: Path) -> None:
    text = path.read_text("utf-8")
    import_line = "from .db_backend import get_tracking_db_connection\n"
    if import_line not in text:
        anchor = "from .config import DATABASE_PATH, LIGHT_RULES\n"
        if anchor not in text:
            raise RuntimeError("models.py config import anchor not found; ORDER layout changed")
        text = text.replace(anchor, anchor + import_line, 1)

    legacy = '''def get_db():\n    """获取数据库连接"""\n    conn = sqlite3.connect(DATABASE_PATH)\n    conn.row_factory = sqlite3.Row\n    return conn\n'''
    cloud = '''def get_db():\n    """获取数据库连接；本机 SQLite，Render Cloud 由 TiDB factory 提供。"""\n    return get_tracking_db_connection()\n'''
    if legacy in text:
        text = text.replace(legacy, cloud, 1)
    elif "return get_tracking_db_connection()" not in text:
        raise RuntimeError("models.py get_db() layout changed; refusing unsafe automatic patch")
    path.write_text(text, "utf-8")


def patch_init(path: Path) -> None:
    text = path.read_text("utf-8")
    line = "from .db_backend import register_cloud_db_connection_factory, get_tracking_db_connection\n"
    if line not in text:
        anchor = "from .data_provider import register_order_data_provider, get_order_data_provider, provider_ready, provider_last_synced_at\n"
        if anchor not in text:
            raise RuntimeError("__init__.py data_provider import anchor not found; ORDER layout changed")
        text = text.replace(anchor, anchor + line, 1)
    path.write_text(text, "utf-8")


def validate_copy(dest: Path) -> None:
    for name in ("__init__.py", "models.py", "config.py", "db_backend.py"):
        if not (dest / name).is_file():
            raise RuntimeError(f"missing copied file: {name}")
    py_compile.compile(str(dest / "db_backend.py"), doraise=True)
    py_compile.compile(str(dest / "models.py"), doraise=True)
    py_compile.compile(str(dest / "__init__.py"), doraise=True)
    shutil.rmtree(dest / "__pycache__", ignore_errors=True)


def git_publish(repo: Path, message: str, push: bool) -> None:
    subprocess.run(["git", "add", "order_tracking"], cwd=repo, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo)
    if diff.returncode == 0:
        print("Git: ORDER source already up to date")
        return
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True)
    if push:
        subprocess.run(["git", "push"], cwd=repo, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="explicit local order_tracking folder")
    ap.add_argument("--git", action="store_true", help="git add + commit")
    ap.add_argument("--push", action="store_true", help="git add + commit + push")
    ap.add_argument("--message", default="Sync latest ORDER source for Render")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[1]
    source = discover_source(repo, args.source)
    dest = repo / "order_tracking"
    if dest.exists() and source == dest.resolve():
        raise SystemExit("Refusing to use the Render vendored folder itself as source")

    print(f"ORDER source: {source}")
    print(f"Render copy:  {dest}")
    print("Local ORDER:  READ-ONLY source; it will not be modified")

    with tempfile.TemporaryDirectory(prefix="order_tracking_vendor_") as td:
        staged = Path(td) / "order_tracking"
        shutil.copytree(source, staged, ignore=ignored)
        (staged / "db_backend.py").write_text(DB_BACKEND, "utf-8")
        patch_models(staged / "models.py")
        patch_init(staged / "__init__.py")
        docs = staged / "docs"
        docs.mkdir(exist_ok=True)
        (docs / "CLOUD_DB_DUAL_MODE.md").write_text(DOC, "utf-8")
        validate_copy(staged)

        backup = repo / ".order_tracking_previous"
        if backup.exists():
            shutil.rmtree(backup)
        if dest.exists():
            dest.rename(backup)
        try:
            shutil.copytree(staged, dest)
        except Exception:
            if dest.exists():
                shutil.rmtree(dest)
            if backup.exists():
                backup.rename(dest)
            raise
        finally:
            if backup.exists():
                shutil.rmtree(backup)

    print("ORDER vendored copy updated safely")
    if args.git or args.push:
        git_publish(repo, args.message, push=args.push)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
