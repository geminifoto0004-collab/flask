# -*- coding: utf-8 -*-
"""Route Aduana query calls through the pull worker when running on Render.

This is intentionally a tiny adapter around the already-proven query.py.  Local
runs without the Render worker keep the original direct APEX behavior.
"""
from __future__ import annotations

from . import collector_queue, query, settings


def install():
    if hasattr(query, "_collector_local_run_periods"):
        return

    query._collector_local_run_periods = query._run_periods

    def _worker_aware_run_periods(periods, aduana, rut, max_workers=None):
        periods = list(periods)
        if settings.WORKER_ENABLED:
            rows, logs, all_ok = collector_queue.submit_and_wait(
                periods,
                aduana,
                rut,
                max_workers=max_workers,
            )
            query._set_last_diagnostics(logs)
            return query.sort_rows(query._dedupe_full_rows(rows)), logs, all_ok

        return query._collector_local_run_periods(
            periods,
            aduana,
            rut,
            max_workers=max_workers,
        )

    query._run_periods = _worker_aware_run_periods


install()
