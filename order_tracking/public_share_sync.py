"""Low-priority background trigger for permanent public share freshness."""
from __future__ import annotations
import threading
import time

_started = False
_lock = threading.Lock()


def schedule_public_share_sync(app, start_delay, interval):
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def runner():
        time.sleep(max(30, int(start_delay)))
        while True:
            try:
                with app.app_context():
                    from .public_share_provider import sync_due_public_shares
                    sync_due_public_shares()
            except Exception as exc:
                print(f'[WARN] public share background sync skipped/failed: {exc}')
            time.sleep(max(3600, int(interval)))

    threading.Thread(target=runner, name='public-share-sync', daemon=True).start()
