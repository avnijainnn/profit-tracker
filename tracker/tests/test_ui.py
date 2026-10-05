from datetime import date
from pathlib import Path
import re
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import SimpleTestCase, TestCase
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
            (reverse("month_review"), ["reason", "confirm"]),
            (reverse("entry_delete", args=[entry.pk]), ["expected_revision", "submission_token"]),
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

    def test_settings_only_show_saved_accounts_and_custom_creation_forms(self):
        response = self.client.get(reverse("settings"))
        self.assertContains(response, "Bank 1")
        self.assertContains(response, "Add account")
        self.assertContains(response, "Add category")
        self.assertNotContains(response, "Starter setup")
        self.assertNotContains(response, "Add starter accounts")
        self.assertNotContains(response, 'value="defaults"')

    def test_expenses_are_added_from_dashboard_and_not_sku_detail(self):
        expense_url = reverse("entry_add", args=["expense"])
        self.assertContains(self.client.get(reverse("dashboard")), expense_url)
        response = self.client.get(reverse("product_detail", args=[self.product.pk]))
        self.assertNotContains(response, expense_url)
        self.assertContains(response, "Stock history")
        self.assertContains(response, "Expenses")

    def test_delete_confirmations_have_explicit_post_targets_and_modal_content(self):
        entry = Entry.objects.create(owner=self.user, kind="income", date=date(2025, 9, 1),
                                     amount=100, account=self.bank, source="cash")
        stock = StockMovement.objects.create(product=self.product, date=date(2025, 9, 1),
                                             kind="received", quantity=5)
        for route, pk in (("entry_delete", entry.pk), ("stock_delete", stock.pk),
                          ("product_delete", self.product.pk)):
            with self.subTest(route=route):
                target = reverse(route, args=[pk]) + "?month=2025-09"
                response = self.client.get(target)
                self.assertContains(response, 'data-delete-confirmation')
                self.assertContains(response, 'data-delete-form')
                self.assertContains(response, 'data-delete-cancel')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                self.assertContains(response, f'action="{target}"')

    def test_closing_summary_matches_three_client_totals(self):
        Entry.objects.create(owner=self.user, kind="income", date=date(2025, 9, 1),
                             amount="100.25", account=self.bank, source="cash")
        Entry.objects.create(owner=self.user, kind="expense", date=date(2025, 9, 1),
                             amount="14.91", account=self.bank,
                             category=Category.objects.get(owner=self.user, name="Manufacturing"))
        response = self.client.get(reverse("month_review"), {"month": "2025-09"})
        self.assertContains(response, "Money received")
        self.assertContains(response, "Profit")
        for amount in ("100.25", "14.91", "85.34"):
            self.assertContains(response, amount)
        self.assertNotContains(response, "Result before withdrawals")
        self.assertNotContains(response, "Result after withdrawals")


class StaticDesignTests(SimpleTestCase):
    def setUp(self):
        self.static = Path(settings.BASE_DIR) / "static" / "tracker"
        self.css = (self.static / "app.css").read_text(encoding="utf-8-sig")

    def test_current_palette_and_surface_roles_are_consistent(self):
        self.assertEqual(set(re.findall(r"#[0-9a-fA-F]{6}\b", self.css)),
                         {"#F8F6EF", "#FFFFFF", "#2F7D5B", "#256447", "#4399D4", "#ED5A54",
                          "#E27798", "#E9B949", "#202522", "#68736D", "#E5E1D8", "#EDF5F0"})
        for declaration in ("--bg: #F8F6EF;", "--panel: #FFFFFF;",
                            "--text: #202522;", "--hover: #EDF5F0;"):
            self.assertIn(declaration, self.css)
        definitions = set(re.findall(r"(--[\w-]+)\s*:", self.css))
        references = set(re.findall(r"var\((--[\w-]+)\)", self.css))
        self.assertEqual(references - definitions, set())
        for removed in ("gradient(", "box-shadow:", "--button-hover"):
            self.assertNotIn(removed, self.css)

    def test_shared_hover_excludes_the_sku_card_link(self):
        hover = re.search(r"/\* Navigation hover.*?\*/\s*:is\((.*?)\):is\(:hover, :focus-visible\)\s*\{(.*?)\}",
                          self.css, re.S)
        self.assertIsNotNone(hover)
        selectors, declarations = hover.groups()
        self.assertIn("a:not(.product-card-link)", selectors)
        self.assertNotIn(".product-card-link", selectors.replace("a:not(.product-card-link)", ""))
        self.assertIn("background: var(--hover)", declarations)
        for selector in (".sidebar nav a", ".entry-tabs a", "summary"):
            self.assertIn(selector, selectors)

    def test_favicon_and_self_hosted_font_assets_are_valid(self):
        svg = ElementTree.parse(self.static / "favicon.svg").getroot()
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertEqual(svg.attrib["viewBox"], "0 0 32 32")
        self.assertGreater((self.static / "fonts" / "Inter-Variable.ttf").stat().st_size, 1000)
        self.assertIn("SIL OPEN FONT LICENSE", (self.static / "fonts" / "OFL.txt").read_text())
