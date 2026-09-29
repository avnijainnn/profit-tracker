import logging
from unittest import TestCase
from config.logging import RedactOperationalLogs


class LoggingPrivacyTests(TestCase):
    def test_financial_values_and_request_removed_from_output(self):
        record = logging.LogRecord("django.request", logging.ERROR, "views.py", 10,
                                   "Payment failed for %s", ("PRIVATE-BANK-REFERENCE",), None)
        record.request = {"password": "PRIVATE-PASSWORD", "amount": "999999"}
        record.status_code = 500
        RedactOperationalLogs().filter(record)
        text = logging.Formatter("{levelname} {name} {message}", style="{").format(record)
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn("999999", text)
        self.assertIn("500", text)
        self.assertIsNone(record.request)

    def test_exception_value_and_cached_traceback_removed(self):
        exception = ValueError("PRIVATE-TRANSACTION-DATA")
        record = logging.LogRecord("django.request", logging.ERROR, "views.py", 10,
                                   "Failure", (), (ValueError, exception, None))
        record.exc_text = "Cached traceback PRIVATE-TRANSACTION-DATA"
        RedactOperationalLogs().filter(record)
        text = logging.Formatter().format(record)
        self.assertIn("ValueError", text)
        self.assertNotIn("PRIVATE", text)
        self.assertIsNone(record.exc_info)
