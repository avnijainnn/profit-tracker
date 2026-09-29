"""Production WSGI server. No URL query strings or request bodies in access logs."""
import os

bind = "0.0.0.0:" + os.environ.get("PORT", "8000")
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "sync"
timeout = 30
max_requests = 1000
max_requests_jitter = 100
accesslog = None
errorlog = "-"
loglevel = "warning"
capture_output = False
