"""Serve guest pages while ORDER sync requests wait for TiDB.

One process keeps the existing in-memory share caches and refresh workers shared.
Four threads let short guest/static requests proceed during network-bound sync.
"""

workers = 1
worker_class = 'gthread'
threads = 4

# Keep the existing access log fields and include actual server request duration.
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" duration_us=%(D)s'
