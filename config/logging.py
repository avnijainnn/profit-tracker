"""No Django imports: logging is configured before Django's app registry is ready."""
import logging


class RedactOperationalLogs(logging.Filter):
    def filter(self, record):
        error_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else "event"
        status = getattr(record, "status_code", "")
        record.msg = "Application event: type=%s status=%s; investigate with synthetic data" % (error_type, status)
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        if hasattr(record, "request"):
            record.request = None
        return True
