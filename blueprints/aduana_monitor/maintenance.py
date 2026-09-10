# -*- coding: utf-8 -*-
"""Admin-only maintenance helpers for Aduana Monitor test/reset operations.

These helpers intentionally touch only Aduana Monitor tables. They never delete
parent FLASK users, Automation Hub bots, or Aduana monitor subscriptions.
"""
from __future__ import annotations

from database import get_db_connection, get_cursor
from utils.time_utils import get_chile_time_naive


def _transaction():
    conn = get_db_connection()
    cur = get_cursor(conn)
    return conn, cur


def reset_scan_history(rut: str | None = None):
    """Delete discovered Aduana data and reset baselines, preserving setup.

    If ``rut`` is provided only that normalized RUT is reset. If omitted, all
    Aduana records/notifications/scan-target state is cleared. Users, monitor
    subscriptions and Automation Hub bot configuration are preserved.
    """
    rut = (rut or "").strip().upper() or None
    conn, cur = _transaction()
    try:
        result = {
            "rut": rut,
            "notifications_deleted": 0,
            "records_deleted": 0,
            "targets_deleted": 0,
            "monitors_reset": 0,
        }

        if rut:
            cur.execute(
                "DELETE FROM aduana_notifications WHERE record_id IN "
                "(SELECT id FROM aduana_records WHERE rut=?)",
                (rut,),
            )
            result["notifications_deleted"] = max(0, int(cur.rowcount or 0))

            cur.execute("DELETE FROM aduana_records WHERE rut=?", (rut,))
            result["records_deleted"] = max(0, int(cur.rowcount or 0))

            cur.execute("DELETE FROM aduana_scan_targets WHERE rut=?", (rut,))
            result["targets_deleted"] = max(0, int(cur.rowcount or 0))

            cur.execute(
                "UPDATE aduana_monitors "
                "SET baseline_done=0, baseline_at=NULL, updated_at=? "
                "WHERE rut=?",
                (get_chile_time_naive(), rut),
            )
            result["monitors_reset"] = max(0, int(cur.rowcount or 0))
        else:
            cur.execute("DELETE FROM aduana_notifications")
            result["notifications_deleted"] = max(0, int(cur.rowcount or 0))

            cur.execute("DELETE FROM aduana_records")
            result["records_deleted"] = max(0, int(cur.rowcount or 0))

            cur.execute("DELETE FROM aduana_scan_targets")
            result["targets_deleted"] = max(0, int(cur.rowcount or 0))

            cur.execute(
                "UPDATE aduana_monitors "
                "SET baseline_done=0, baseline_at=NULL, updated_at=?",
                (get_chile_time_naive(),),
            )
            result["monitors_reset"] = max(0, int(cur.rowcount or 0))

        conn.commit()
        return result
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def clear_finished_runs():
    """Clear old run history without deleting an active RUNNING lock."""
    conn, cur = _transaction()
    try:
        cur.execute("DELETE FROM aduana_runs WHERE status <> 'RUNNING'")
        deleted = max(0, int(cur.rowcount or 0))
        conn.commit()
        return deleted
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
