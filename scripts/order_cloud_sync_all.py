#!/usr/bin/env python3
"""Background-safe full/incremental ORDER -> Render/TiDB sync.

Important safety properties:
- ORDER SQLite is opened read-only and PRAGMA query_only=ON is inherited from
  order_cloud_sync_real_order.py.
- Only that module's explicit customer-safe payload is sent.
- This script NEVER scans/uploads images, PDFs, Access, phone numbers, deposits,
  payments, internal notes, local file paths, or original filenames.
- State is stored outside tracking.db so normal local ORDER business work is not
  modified or locked by the sync process.

First run uploads all current cloud-safe orders. Later runs hash the same safe
payload and send only new/changed orders. Orders present in the previous successful
local index but no longer present in SQLite are hard-deleted from TiDB so cloud
presence matches local SQLite rather than accumulating soft-deleted rows.

Network writes are parallelised with a small bounded worker pool. This avoids the
very slow one-request-at-a-time first sync without overwhelming Render/TiDB.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Dict, Tuple

import order_cloud_sync_real_order as one

STATE_VERSION = 1
DEFAULT_WORKERS = 4
MAX_WORKERS = 8


def _state_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = (os.environ.get("ORDER_CLOUD_SYNC_STATE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "XingwangOrder" / "order_cloud_sync_state.json"


def _load_state(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text("utf-8"))
        if isinstance(raw, dict) and raw.get("version") == STATE_VERSION:
            raw.setdefault("fingerprints", {})
            return raw
    except FileNotFoundError:
        pass
    except Exception:
        # Corrupt/mismatched state must never block ORDER; rebuild by full safe sync.
        pass
    return {"version": STATE_VERSION, "fingerprints": {}, "last_success_at": None}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
    fd, temp_name = tempfile.mkstemp(prefix="order_cloud_sync_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.remove(temp_name)
        except OSError:
            pass


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _order_numbers(conn) -> list[str]:
    cols = one._columns(conn, "orders")
    if "order_number" not in cols:
        raise one.SyncError("orders.order_number is missing")
    order_by = []
    if "order_date" in cols:
        order_by.append("order_date ASC")
    if "created_at" in cols:
        order_by.append("created_at ASC")
    order_by.append("order_number ASC")
    rows = conn.execute(
        "SELECT order_number FROM orders WHERE order_number IS NOT NULL ORDER BY " + ", ".join(order_by)
    ).fetchall()
    result = []
    seen = set()
    for row in rows:
        value = str(row[0] or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _recent_success(state: dict, min_interval_minutes: int) -> bool:
    if min_interval_minutes <= 0:
        return False
    raw = state.get("last_success_at")
    if not raw:
        return False
    try:
        then = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - then.astimezone(timezone.utc)
        return age.total_seconds() < min_interval_minutes * 60
    except Exception:
        return False


def _send_job(job: dict) -> dict:
    body = one._request_json("POST", "/api/order-cloud/sync/order", json=job["payload"])
    if not body.get("ok"):
        raise one.SyncError(str(body.get("error") or "Render rejected ORDER sync"))
    return body


def sync_all(
    db_path: str | None,
    state_path: Path,
    full: bool,
    quiet: bool,
    min_interval_minutes: int,
    workers: int = DEFAULT_WORKERS,
) -> Tuple[int, int, int]:
    state = _load_state(state_path)
    if not full and _recent_success(state, min_interval_minutes):
        if not quiet:
            print(f"ORDER cloud sync skipped: last success < {min_interval_minutes} minutes")
        return 0, 0, 0

    # Fail fast before scanning hundreds/thousands of local orders. This avoids
    # repeated network attempts when Render/TiDB is temporarily unavailable.
    health = one._request_json("GET", "/api/order-cloud/health")
    if not health.get("ok"):
        raise one.SyncError(str(health.get("error") or "Render ORDER cloud gateway is not ready"))

    db = one._discover_db(db_path)
    conn = one._open_read_only(db)
    try:
        numbers = _order_numbers(conn)
        current_numbers = set(numbers)
        if not quiet:
            print(f"ORDER SQLite: {db}")
            print(f"Orders scanned: {len(numbers)}")
            print("Images/PDF/Access: NOT READ / NOT SENT")

        fingerprints: Dict[str, str] = dict(state.get("fingerprints") or {})
        previous_numbers = set(fingerprints)
        deleted_numbers = sorted(previous_numbers - current_numbers)

        jobs: list[dict] = []
        unchanged = 0
        skipped_no_customer = 0
        prepare_failed = 0

        # Build payloads locally first. SQLite work stays single-threaded/read-only;
        # only the HTTP/TiDB writes are parallel below.
        for order_number in numbers:
            try:
                payload = one._load_order_payload(conn, order_number)
                fingerprint = _payload_hash(payload)
                if not full and fingerprints.get(order_number) == fingerprint:
                    unchanged += 1
                    continue
                jobs.append({
                    "order_number": order_number,
                    "payload": payload,
                    "fingerprint": fingerprint,
                    "delete": False,
                })
            except one.SyncError as exc:
                # Legacy/placeholder ORDER rows with no customer cannot be represented
                # in the customer-keyed cloud mirror. They are source-data omissions,
                # not network/TiDB failures. If this order was previously synced while
                # it had a customer, delete that stale cloud copy.
                if "has no customer_name" in str(exc):
                    skipped_no_customer += 1
                    if order_number in fingerprints:
                        jobs.append({
                            "order_number": order_number,
                            "payload": {"order_number": order_number, "_deleted": True},
                            "fingerprint": None,
                            "delete": True,
                        })
                    continue
                prepare_failed += 1
                if not quiet:
                    print(f"PREPARE FAILED: {order_number}: {type(exc).__name__}: {exc}")
            except Exception as exc:
                prepare_failed += 1
                if not quiet:
                    print(f"PREPARE FAILED: {order_number}: {type(exc).__name__}: {exc}")

        # Orders removed from SQLite are hard-deleted from TiDB.
        already_delete = {j["order_number"] for j in jobs if j["delete"]}
        for order_number in deleted_numbers:
            if order_number in already_delete:
                continue
            jobs.append({
                "order_number": order_number,
                "payload": {"order_number": order_number, "_deleted": True},
                "fingerprint": None,
                "delete": True,
            })

        if not quiet:
            print(
                f"Cloud writes queued: {len(jobs)} | unchanged={unchanged} | "
                f"no_customer={skipped_no_customer} | workers={workers}"
            )

        sent = 0
        deleted = 0
        failed = prepare_failed
        completed = 0
        total_jobs = len(jobs)
        workers = max(1, min(MAX_WORKERS, int(workers or DEFAULT_WORKERS)))

        if jobs:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="order-cloud-sync") as pool:
                future_map = {pool.submit(_send_job, job): job for job in jobs}
                for future in as_completed(future_map):
                    job = future_map[future]
                    completed += 1
                    try:
                        future.result()
                        if job["delete"]:
                            fingerprints.pop(job["order_number"], None)
                            deleted += 1
                        else:
                            fingerprints[job["order_number"]] = job["fingerprint"]
                            sent += 1

                        # Save progress regularly so Ctrl+C/network interruption does
                        # not make the next run start from zero.
                        if completed % 25 == 0:
                            state["fingerprints"] = fingerprints
                            _save_state(state_path, state)

                        if not quiet and (completed % 25 == 0 or completed == total_jobs):
                            print(
                                f"PROGRESS {completed}/{total_jobs}: "
                                f"sent={sent} deleted={deleted} failed={failed}"
                            )
                    except Exception as exc:
                        failed += 1
                        if not quiet:
                            action = "DELETE" if job["delete"] else "SYNC"
                            print(
                                f"{action} FAILED: {job['order_number']}: "
                                f"{type(exc).__name__}: {exc}"
                            )

        state["fingerprints"] = fingerprints
        state["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
        if failed == 0:
            state["last_success_at"] = state["last_attempt_at"]
        state["last_db"] = str(db)
        state["last_order_count"] = len(numbers)
        state["last_skipped_no_customer"] = skipped_no_customer
        _save_state(state_path, state)

        if not quiet:
            print(
                f"ORDER CLOUD SYNC SUMMARY: sent={sent} unchanged={unchanged} "
                f"deleted={deleted} no_customer={skipped_no_customer} failed={failed}"
            )
        return sent, unchanged, failed
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="explicit local tracking.db path")
    ap.add_argument("--state", help="explicit local fingerprint state JSON path")
    ap.add_argument("--full", action="store_true", help="send every cloud-safe order even if fingerprint is unchanged")
    ap.add_argument("--quiet", action="store_true", help="print only unexpected top-level errors")
    ap.add_argument(
        "--min-interval-minutes",
        type=int,
        default=int(os.environ.get("ORDER_CLOUD_AUTOSYNC_MIN_MINUTES", "30")),
        help="skip startup sync if a successful sync was this recent (default 30)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("ORDER_CLOUD_SYNC_WORKERS", str(DEFAULT_WORKERS))),
        help=f"parallel Render/TiDB write requests (default {DEFAULT_WORKERS}, max {MAX_WORKERS})",
    )
    args = ap.parse_args()

    try:
        _sent, _unchanged, failed = sync_all(
            args.db,
            _state_path(args.state),
            full=bool(args.full),
            quiet=bool(args.quiet),
            min_interval_minutes=max(0, int(args.min_interval_minutes)),
            workers=max(1, min(MAX_WORKERS, int(args.workers))),
        )
        return 1 if failed else 0
    except KeyboardInterrupt:
        print("ORDER CLOUD SYNC CANCELLED", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ORDER CLOUD SYNC ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
