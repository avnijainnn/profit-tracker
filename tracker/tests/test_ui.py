from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tracker.models import Account, Category, Entry, Product, StockMovement
from tracker.services import setup_defaults


class FormRenderingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("ui-owner")
        setup_defaults(self.user)
        self.client.force_login(self.user)
        self.bank = Account.objects.get(owner=self.user, name="Bank 1")
        self.product = Product.objects.create(owner=self.user, sku="UI", name="UI bag")

    def test_forms_without_optional_field_configuration_render_their_inputs(self):
        entry = Entry.objects.create(owner=self.user, kind="income", date=date(2025, 9, 1),
                                     amount=100, account=self.bank, source="cash")
        stock = StockMovement.objects.create(product=self.product, date=date(2025, 9, 1),
                                             kind="received", quantity=5)
        cases = [
            (reverse("settings"), ["account-name", "account-kind", "category-name"]),
            (reverse("product_add"), ["sku", "name", "kind", "notes"]),
            (reverse("bank_tally"), ["statement_credits", "statement_debits", "notes"]),
            (reverse("month_review"), ["reason", "confirm"]),
            (reverse("entry_void", args=[entry.pk]), ["reason", "confirm"]),
            (reverse("stock_reverse", args=[stock.pk]), ["reason", "confirm"]),
        ]
        for url, fields in cases:
            with self.subTest(url=url):
                response = self.client.get(url, {"month": "2025-09"})
                for name in fields:
                    self.assertContains(response, f'name="{name}"')

    def test_month_survives_settings_and_history_navigation(self):
        self.client.get(reverse("dashboard"), {"month": "2025-09"})
        for route in ("settings", "history", "products", "dashboard"):
            response = self.client.get(reverse(route))
            self.assertContains(response, "?month=2025-09")
        response = self.client.get(reverse("dashboard"), {"month": "not-a-month"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "not-a-month")

    def test_inline_category_creation_keeps_incomplete_form_and_exposes_errors(self):
        url = reverse("entry_add", args=["expense"])
        response = self.client.post(url, {"inline_action": "category", "category-name": "Custom label", "amount": "42.00"})
        self.assertEqual(Entry.objects.count(), 0)
        self.assertTrue(Category.objects.filter(owner=self.user, name="Custom label").exists())
        self.assertContains(response, 'value="42.00"')
        self.assertContains(response, "formnovalidate")
        response = self.client.post(url, {"inline_action": "category", "category-name": "Custom label"})
        self.assertContains(response, 'class="inline-create" open')
        self.assertContains(response, "This category already exists.")

    def test_dropdowns_have_meaningful_empty_labels(self):
        response = self.client.get(reverse("entry_add", args=["expense"]))
        self.assertContains(response, "Choose a category")
        self.assertContains(response, "No product linked (optional)")
        self.assertNotContains(response, "---------")
