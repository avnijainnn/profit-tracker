"""Regression checks for the simplified client workflow and archived SKUs."""
from datetime import date
from decimal import Decimal
from io import StringIO
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tracker.forms import EntryForm
from tracker.models import Account, Category, ChangeLog, Entry, MonthReview, Product
from tracker.services import add_stock, save_entry, setup_defaults
from tracker.summaries import monthly_totals, payment_totals, yearly_totals


class CurrentFlowTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("current-owner")
        self.other = get_user_model().objects.create_user("private-owner")
        setup_defaults(self.owner)
        self.bank = Account.objects.get(owner=self.owner, name="Bank 1")
        self.category = Category.objects.get(owner=self.owner, name="Manufacturing")
        self.product = Product.objects.create(owner=self.owner, sku="CURRENT", name="Current bag")
        self.client.force_login(self.owner)

    def data(self, **changes):
        return {"date": "2025-08-22", "amount": "25.99", "category": self.category.pk,
                "account": self.bank.pk, "product": self.product.pk,
                "expected_revision": 0, "submission_token": uuid.uuid4(), **changes}

    def test_delete_sku_preserves_expenses_stock_and_retries_once(self):
        self.client.post(reverse("entry_add", args=["expense"]), self.data())
        add_stock(self.product, self.owner, {"date": date(2025, 9, 1), "kind": "received", "quantity": 4})
        url = reverse("product_delete", args=[self.product.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.product.refresh_from_db()
        self.assertTrue(self.product.active)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.product.refresh_from_db()
        self.assertFalse(self.product.active)
        self.assertEqual(ChangeLog.objects.filter(action="product_deleted").count(), 1)
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(self.product.movements.count(), 1)
        self.assertEqual(monthly_totals(self.owner, date(2025, 8, 1), date(2025, 9, 1))["expense"], Decimal("25.99"))
        self.assertNotContains(self.client.get(reverse("products")), "Current bag")

    def test_deleted_sku_cannot_receive_new_entries_but_old_expense_remains_editable(self):
        self.client.post(reverse("entry_add", args=["expense"]), self.data())
        entry = Entry.objects.get()
        stale_form = EntryForm(self.data(submission_token=uuid.uuid4()), owner=self.owner, kind="expense")
        self.assertTrue(stale_form.is_valid(), stale_form.errors)
        self.client.post(reverse("product_delete", args=[self.product.pk]))
        with self.assertRaises(ValidationError):
            save_entry(stale_form, self.owner)
        with self.assertRaises(ValidationError):
            add_stock(self.product, self.owner, {"date": date(2025, 9, 1), "kind": "received", "quantity": 4})
        self.assertEqual(self.client.get(reverse("stock_add", args=[self.product.pk])).status_code, 404)
        response = self.client.post(reverse("entry_edit", args=[entry.pk]), self.data(
            amount="40.01", expected_revision=entry.revision))
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.amount, Decimal("40.01"))

    def test_sku_delete_is_owner_scoped_and_csrf_protected(self):
        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        url = reverse("product_delete", args=[self.product.pk])
        self.assertEqual(csrf_client.post(url).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.product.refresh_from_db()
        self.assertTrue(self.product.active)

    def test_automatic_summaries_agree_for_decimal_values_months_voids_and_owners(self):
        accounts = list(Account.objects.filter(owner=self.owner).exclude(kind="other"))
        expected = {m: {"income": Decimal("0.00"), "expense": Decimal("0.00")} for m in range(1, 13)}
        entries = []
        for index in range(1200):
            month = index % 12 + 1
            kind = "income" if index % 5 < 2 else "expense"
            amount = Decimal(index % 157 + 1) / 100
            is_void = index % 19 == 0
            entries.append(Entry(owner=self.owner, date=date(2025, month, 15), kind=kind, amount=amount,
                account=accounts[index % len(accounts)], source="cash" if kind == "income" else "",
                category=self.category if kind == "expense" else None,
                voided_at=timezone.now() if is_void else None))
            if not is_void:
                expected[month][kind] += amount
        Entry.objects.bulk_create(entries)
        foreign_bank = Account.objects.create(owner=self.other, name="Private")
        Entry.objects.create(owner=self.other, date=date(2025, 8, 15), kind="income", amount=999,
                             account=foreign_bank, source="cash")
        yearly = yearly_totals(self.owner, 2025)
        for month, amounts in expected.items():
            start = date(2025, month, 1)
            end = date(2026, 1, 1) if month == 12 else date(2025, month + 1, 1)
            monthly = monthly_totals(self.owner, start, end)
            payments = payment_totals(self.owner, start, end)["totals"]
            self.assertEqual(monthly["income"], amounts["income"])
            self.assertEqual(monthly["expense"], amounts["expense"])
            self.assertEqual(monthly["result"], amounts["income"] - amounts["expense"])
            self.assertEqual(yearly[month], monthly)
            self.assertEqual(payments, {"received": amounts["income"], "expenses": amounts["expense"]})

    def test_navigation_only_offers_requested_tools_and_direct_export(self):
        response = self.client.get(reverse("dashboard"), {"month": "2025-08"})
        self.assertContains(response, "Export month CSV")
        self.assertContains(response, "Close month")
        for removed in ("More actions", "Change history", "Month review", "Owner withdrawal", "Transfer / repayment"):
            self.assertNotContains(response, removed)
        self.assertContains(response, "Payment summary")

    def test_malformed_account_and_product_parameters_return_404(self):
        for value in ("invalid", "1.5", "1 OR 1=1"):
            self.assertEqual(self.client.get(reverse("payment_summary"), {"account": value}).status_code, 404)
            self.assertEqual(self.client.get(reverse("entry_add", args=["expense"]), {"product": value}).status_code, 404)

    def test_audit_command_is_read_only_and_passes_valid_data(self):
        ChangeLog.objects.create(owner=self.owner, action="defaults_added", object_label="Starter data")
        MonthReview.objects.create(owner=self.owner, month=date(2025, 9, 1))
        self.client.post(reverse("entry_add", args=["expense"]), self.data())
        before = (Entry.objects.count(), ChangeLog.objects.count())
        output = StringIO()
        call_command("audit_data", stdout=output)
        self.assertIn("Audit passed", output.getvalue())
        self.assertEqual((Entry.objects.count(), ChangeLog.objects.count()), before)
