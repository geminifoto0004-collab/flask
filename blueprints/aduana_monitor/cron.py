# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import query, settings, storage, telegram

log = logging.getLogger(__name__)
_BATCH_THREAD_LOCK = threading.Lock()
_BATCH_THREAD_ACTIVE = False


def _format_record_message(row):
    label = settings.ADUANA_LABELS.get(row.get("aduana"), row.get("aduana") or "")
    esc = telegram.escape_html
    return (
        "⚠️ <b>NUEVA DENUNCIA ADUANA</b>\n\n"
        f"RUT: <b>{esc(row.get('rut'))}</b>\n"
        f"Aduana: <b>{esc(label)}</b>\n\n"
        f"N° Denuncia: <b>{esc(row.get('n_denuncia'))}</b>\n"
        f"Emisión: {esc(row.get('emision'))}\n"
        f"Notificación: {esc(row.get('notificacion'))}\n"
        f"Doc. Aduanero: {esc(row.get('doc_aduanero'))}\n"
        f"Art. Infracción: {esc(row.get('art_infraccion'))}\n"
        f"Infractor: {esc(row.get('infractor'))}\n\n"
        f"Multa Máx. Legal: {esc(row.get('multa_max_legal'))}\n"
        f"Multa c/Allan.: {esc(row.get('multa_c_allan'))}\n"
        f"Multa s/Allan.: {esc(row.get('multa_s_allan'))}\n"
        f"Venc. Allan.: {esc(row.get('venc_allan'))}\n"
        f"Venc. Recl. Junta: {esc(row.get('venc_recl_junta'))}"
    )


def _process_one_target(rut, aduana, subscriptions):
    try:
        rows, logs, all_ok = query.query_last_n_days(
            settings.CRON_LOOKBACK_DAYS, aduana, rut, max_workers=1
        )
        if not all_ok:
            storage.mark_target_failure(rut, aduana, logs)
            return {"ok": False, "rut": rut, "aduana": aduana, "rows": 0, "new": 0, "error": "partial_or_failed_scan"}
        new_count = storage.apply_successful_scan(rut, aduana, rows, subscriptions, query.row_hash)
        return {"ok": True, "rut": rut, "aduana": aduana, "rows": len(rows), "new": new_count}
    except Exception as exc:
        log.exception("Aduana target failed: %s/%s", rut, aduana)
        try:
            storage.mark_target_failure(rut, aduana, [{"estado": "REQUEST_FAILED", "error": str(exc)}])
        except Exception:
            pass
        return {"ok": False, "rut": rut, "aduana": aduana, "rows": 0, "new": 0, "error": str(exc)}


def _send_pending_notifications():
    sent = failed = 0
    for item in storage.pending_notifications(limit=1000):
        notif_id = item["id"]
        attempts = int(item.get("attempts") or 0) + 1
        if item.get("user_status") != "ACTIVE" or not bool(item.get("can_monitor")) or not bool(item.get("monitor_enabled")):
            storage.mark_notification(notif_id, "SKIPPED", attempts, "Usuario o monitoreo inactivo")
            continue
        try:
            telegram.send_message(item["chat_id"], _format_record_message(item))
            storage.mark_notification(notif_id, "SENT", attempts, None, storage.now())
            sent += 1
        except Exception as exc:
            storage.mark_notification(notif_id, "FAILED", attempts, str(exc)[:2000])
            failed += 1
    return sent, failed


def run_check_all():
    run_id, existing = storage.try_start_run()
    if run_id is None:
        return {"ok": False, "locked": True, "run": existing}

    targets = storage.active_targets()
    target_items = list(targets.items())
    total_rows = total_new = 0
    failed_targets = []

    try:
        if target_items:
            with ThreadPoolExecutor(max_workers=min(settings.TARGET_WORKERS, len(target_items))) as executor:
                futures = {
                    executor.submit(_process_one_target, rut, aduana, subscriptions): (rut, aduana)
                    for (rut, aduana), subscriptions in target_items
                }
                for future in as_completed(futures):
                    result = future.result()
                    total_rows += int(result.get("rows") or 0)
                    total_new += int(result.get("new") or 0)
                    if not result.get("ok"):
                        failed_targets.append(f"{result.get('rut')}/{result.get('aduana')}: {result.get('error')}")

        sent, failed_notifications = _send_pending_notifications()
        status = "PARTIAL" if failed_targets else "SUCCESS"
        storage.finish_run(
            run_id,
            status=status,
            targets_checked=len(target_items) - len(failed_targets),
            unique_queries=len(target_items),
            records_found=total_rows,
            new_records=total_new,
            sent=sent,
            failed=failed_notifications,
            error="; ".join(failed_targets)[:4000] if failed_targets else None,
        )
        return {
            "ok": not failed_targets,
            "status": status,
            "run_id": run_id,
            "targets": len(target_items),
            "rows": total_rows,
            "new": total_new,
            "sent": sent,
            "failed_notifications": failed_notifications,
            "failed_targets": len(failed_targets),
        }
    except Exception as exc:
        log.exception("Aduana batch failed")
        storage.finish_run(run_id, status="FAILED", unique_queries=len(target_items), error=str(exc)[:4000])
        return {"ok": False, "status": "FAILED", "run_id": run_id, "error": str(exc)}


def _background_entry():
    global _BATCH_THREAD_ACTIVE
    try:
        run_check_all()
    finally:
        with _BATCH_THREAD_LOCK:
            _BATCH_THREAD_ACTIVE = False


def start_background_batch():
    global _BATCH_THREAD_ACTIVE
    with _BATCH_THREAD_LOCK:
        if _BATCH_THREAD_ACTIVE:
            return False
        _BATCH_THREAD_ACTIVE = True
        threading.Thread(target=_background_entry, daemon=True, name="aduana-cron").start()
        return True
