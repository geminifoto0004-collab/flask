"""Install passive B2 SDK counters on the existing Flask blueprint."""
from blueprints.b2_test_bp import b2_test_bp
from services.order_b2_metrics import log_pending


@b2_test_bp.after_app_request
def _flush_order_b2_metrics(response):
    # Observability must never change customer pages, status codes, or uploads.
    try:
        log_pending()
    except Exception as exc:
        print(f"[ORDER B2 USAGE] logging_error={type(exc).__name__}", flush=True)
    return response
