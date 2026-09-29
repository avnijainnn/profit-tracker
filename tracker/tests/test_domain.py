"""These tests run with standard Python even before Django is installed."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from tracker.domain import month_bounds, safe_csv_cell, statement_summary, stock_delta, validate_stock_timeline


class DomainTests(TestCase):
    def entry(self, kind, amount, voided=False):
        return SimpleNamespace(kind=kind, amount=Decimal(amount), voided_at=date(2025, 9, 1) if voided else None)

    def test_razorpay_receipts_accumulate_exactly(self):
        result = statement_summary([self.entry("income", "0.10"), self.entry("income", "0.20")])
        self.assertEqual(result["income"], Decimal("0.30"))

    def test_transfers_and_repayments_never_count_twice(self):
        result = statement_summary([self.entry("income", "10000"), self.entry("expense", "3500"), self.entry("transfer", "3500")])
        self.assertEqual(result["expense"], Decimal("3500"))
        self.assertEqual(result["result"], Decimal("6500"))

    def test_owner_withdrawal_separate(self):
        result = statement_summary([self.entry("income", "10000"), self.entry("expense", "2000"), self.entry("withdrawal", "3000")])
        self.assertEqual(result["result"], Decimal("8000"))
        self.assertEqual(result["after_withdrawals"], Decimal("5000"))

    def test_voided_entries_excluded(self):
        self.assertEqual(statement_summary([self.entry("income", "1000", voided=True)])["income"], Decimal("0"))

    def test_calendar_boundary(self):
        self.assertEqual(month_bounds("2025-12"), (date(2025, 12, 1), date(2026, 1, 1)))
        self.assertEqual(month_bounds("2024-02"), (date(2024, 2, 1), date(2024, 3, 1)))

    def test_bad_month(self):
        for value in ("2025-13", "2025-1", "anything", "2025-00", "0000-01"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                month_bounds(value)

    def test_stock_quantities_and_returns(self):
        movements = [SimpleNamespace(kind=k, quantity=q) for k, q in (("received", 50), ("sold", 12), ("returned", 1), ("damaged", 2))]
        self.assertEqual(validate_stock_timeline(movements), 37)

    def test_stock_never_negative_at_earlier_date(self):
        with self.assertRaises(ValueError):
            validate_stock_timeline([SimpleNamespace(kind="sold", quantity=2), SimpleNamespace(kind="received", quantity=10)])

    def test_invalid_stock(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                stock_delta("received", value)
        with self.assertRaises(ValueError):
            stock_delta("made_up", 1)

    def test_csv_formula_injection(self):
        for value in ("=SUM(A1)", " +1", "-2+3", "@CMD", "\t=1", "\n=1"):
            with self.subTest(value=value):
                self.assertTrue(safe_csv_cell(value).startswith("'"))
        self.assertEqual(safe_csv_cell("Aqua Babe"), "Aqua Babe")
