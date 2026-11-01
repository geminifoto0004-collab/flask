"""Memory-conscious Gunicorn settings for the 512-MiB Render Free instance.

Keep one process so existing share cache and background coordination remain
process-local; recycle it periodically to bound long-lived fragmentation.
The crawler runs in its separate Render service.
"""
import os

workers = 1
worker_class = "gthread"
# Allow a short guest/share request during network-bound ORDER sync, without
# running four simultaneous memory-heavy requests on a 512-MiB instance.
threads = max(2, min(4, int(os.getenv("FLASK_GUNICORN_THREADS", "2"))))
# Gracefully replace a worker after several hundred requests rather than
# keeping growing caches alive indefinitely. Jitter avoids fixed timing.
max_requests = max(100, int(os.getenv("FLASK_GUNICORN_MAX_REQUESTS", "300")))
max_requests_jitter = 60
preload_app = False

# Keep the existing access log fields and include actual request duration.
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" duration_us=%(D)s'
