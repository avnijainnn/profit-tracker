"""Headless browser checks for the current client UI, using an isolated test database."""
import os
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import re
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from PIL import Image
from playwright.sync_api import sync_playwright, expect

from tracker.models import Account, Category, Entry, MonthReview, Product, StockMovement
from tracker.services import add_stock, setup_defaults


@override_settings(DEBUG=True, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class BrowserWorkflows(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        expect.set_options(timeout=30000)
        # The local test server does not need an external reverse-DNS lookup.
        with patch("socket.getfqdn", return_value="localhost"):
            super().setUpClass()
        # Keep one browser process, with a fresh isolated context per test.
        async_patch = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        async_patch.start()
        cls.addClassCleanup(async_patch.stop)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL", "msedge"))
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.user = get_user_model().objects.create_user("browser_tester", "tester@example.test", "BrowserOnly!2026")
        setup_defaults(self.user)
        self.bank = Account.objects.get(owner=self.user, name="Bank 1")
        self.category = Category.objects.get(owner=self.user, name="Manufacturing")
        self.product = Product.objects.create(owner=self.user, sku="QA-BAG", name="Sample bag")
        self.errors = []
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(30000)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("response", self.record_error_response)
        self.login()

    def record_error_response(self, response):
        if response.status >= 400 and not response.url.endswith("/favicon.ico"):
            self.errors.append(f"HTTP {response.status}: {response.url}")

    def tearDown(self):
        if hasattr(self, "page") and not self.page.is_closed():
            folder = Path(tempfile.gettempdir()) / "profit-tracker-ui-review"
            folder.mkdir(exist_ok=True)
            self.page.screenshot(path=str(folder / f"{self._testMethodName}.png"), full_page=True)
        self.assertEqual(self.errors, [], "Browser errors")

    def heading(self, name):
        expect(self.page.get_by_role("heading", name=name, exact=True)).to_be_visible()

    def login(self):
        self.page.goto(self.live_server_url + "/login/")
        self.page.get_by_label("Email").fill("tester@example.test")
        self.page.get_by_label(re.compile(r"^Password:?$")).fill("BrowserOnly!2026")
        self.page.get_by_role("button", name="Sign in", exact=True).click()
        self.heading("Entries")

    def go(self, path):
        self.page.goto(self.live_server_url + path, wait_until="domcontentloaded")

    def open_tools(self):
        tools = self.page.locator(".sidebar-tools")
        if tools.get_attribute("open") is None:
            tools.locator("summary").click()

    def money_form(self, kind, amount="1000"):
        self.go(f"/transactions/new/{kind}/?month=2025-09")
        self.page.locator("#id_date").fill("2025-09-12")
        self.page.locator("#id_amount").fill(amount)
        self.page.locator("#id_account").select_option(str(self.bank.pk))
        if kind == "income":
            self.page.locator("#id_source").select_option("razorpay")
        else:
            self.page.locator("#id_category").select_option(str(self.category.pk))

    def save_entry(self):
        self.page.get_by_role("button", name="Save entry", exact=True).click()
        self.heading("September 2025")
        expect(self.page.get_by_text("Entry saved.", exact=True)).to_be_visible()

    def test_inline_category_account_edit_delete_and_save_another(self):
        self.money_form("expense", "4250")
        expect(self.page.locator("[data-paid-by]")).to_be_hidden()
        self.page.get_by_text("Add a category", exact=True).click()
        self.page.locator("#id_category-name").fill("Browser packaging")
        self.page.get_by_role("button", name="Create and select category").click()
        expect(self.page.locator("#id_category option:checked")).to_have_text("Browser packaging")
        expect(self.page.locator("#id_amount")).to_have_value("4250")
        self.page.get_by_text("Add a payment account", exact=True).click()
        self.page.locator("#id_account-name").fill("Browser wallet")
        self.page.locator("#id_account-kind").select_option("wallet")
        self.page.get_by_role("button", name="Create and select account").click()
        expect(self.page.locator("#id_account option:checked")).to_have_text("Browser wallet")
        self.assertEqual(Entry.objects.count(), 0)
        self.page.get_by_role("button", name="Save & add another").click()
        expect(self.page.locator("#id_amount")).to_have_value("")
        self.page.locator("#id_date").fill("2025-09-13")
        self.page.locator("#id_amount").fill("250")
        self.save_entry()
        self.assertEqual(Entry.objects.count(), 2)
        self.page.get_by_role("link", name="Edit", exact=True).first.click()
        expect(self.page.locator("#id_amount")).to_have_value("250.00")
        self.page.locator("#id_amount").fill("200.01")
        self.page.get_by_text("Optional details", exact=True).click()
        self.page.get_by_label("Reason for correction").fill("Correct amount")
        self.save_entry()
        self.page.get_by_role("link", name="Delete", exact=True).first.click()
        self.page.get_by_role("link", name="Cancel", exact=True).click()
        self.heading("September 2025")
        self.page.get_by_role("link", name="Delete", exact=True).first.click()
        self.page.get_by_role("button", name="Delete entry", exact=True).click()
        expect(self.page.get_by_text("Entry deleted.", exact=True)).to_be_visible()
        self.heading("September 2025")
        self.assertEqual(Entry.objects.filter(voided_at__isnull=True).count(), 1)

    def test_sku_photo_stock_edit_delete_and_separate_payment_month(self):
        self.go("/products/?month=2025-09")
        self.page.get_by_role("link", name=re.compile("Add SKU")).click()
        self.page.get_by_label("SKU / design code").fill("QA-NEW")
        self.page.locator("#id_name").fill("New test bag")
        buffer = BytesIO()
        Image.new("RGB", (32, 32), "pink").save(buffer, format="PNG")
        self.page.locator("#id_photo").set_input_files({"name": "bag.png", "mimeType": "image/png", "buffer": buffer.getvalue()})
        self.page.get_by_role("button", name="Save SKU", exact=True).click()
        self.heading("New test bag")
        expect(self.page.locator("img.product-photo")).to_be_visible()
        product = Product.objects.get(sku="QA-NEW")
        self.money_form("expense", "35.25")
        self.page.locator("#id_date").fill("2025-08-22")
        self.page.locator("#id_product").select_option(str(product.pk))
        self.page.get_by_role("button", name="Save entry", exact=True).click()
        self.heading("August 2025")
        self.go(f"/products/{product.pk}/?month=2025-09")
        self.page.get_by_role("link", name=re.compile("Receive stock")).click()
        self.page.locator("#id_date").fill("2025-09-01")
        self.page.locator("#id_quantity").fill("10")
        self.page.get_by_role("button", name="Receive stock", exact=True).click()
        self.heading("New test bag")
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(Entry.objects.get().date, date(2025, 8, 22))
        self.page.get_by_role("link", name=re.compile("Record units sold")).click()
        self.page.locator("#id_date").fill("2025-09-12")
        self.page.locator("#id_quantity").fill("11")
        self.page.get_by_role("button", name="Record units sold", exact=True).click()
        expect(self.page.get_by_text("This would make stock negative.", exact=False)).to_be_visible()
        self.page.locator("#id_quantity").fill("3")
        self.page.get_by_role("button", name="Record units sold", exact=True).click()
        self.heading("New test bag")
        sold = self.page.get_by_role("row").filter(has_text="Sold")
        sold.get_by_role("link", name="Edit", exact=True).click()
        self.page.locator("#id_quantity").fill("2")
        self.page.get_by_role("button", name="Save stock", exact=True).click()
        self.heading("New test bag")
        self.assertEqual(StockMovement.objects.get(kind="sold").quantity, 2)
        self.page.get_by_role("row").filter(has_text="Sold").get_by_role("link", name="Delete", exact=True).click()
        self.page.get_by_role("button", name="Delete stock entry").click()
        expect(self.page.get_by_text("Stock entry deleted.", exact=True)).to_be_visible()
        self.heading("New test bag")
        self.page.get_by_role("link", name="Edit SKU", exact=True).click()
        self.page.locator("#id_name").fill("Updated test bag")
        self.page.get_by_role("button", name="Save SKU", exact=True).click()
        self.heading("Updated test bag")
        self.page.get_by_role("link", name="Delete SKU", exact=True).click()
        self.page.get_by_role("button", name="Delete SKU", exact=True).click()
        self.heading("Products & stock")
        self.assertFalse(Product.objects.get(pk=product.pk).active)
        self.assertEqual(Entry.objects.count(), 1)
        expect(self.page.locator(".product-card").get_by_text("Updated test bag", exact=True)).to_have_count(0)

    def test_payment_summary_year_report_export_close_reopen(self):
        self.money_form("income", "10000")
        self.save_entry()
        self.money_form("expense", "2000.25")
        self.save_entry()
        self.open_tools()
        self.page.get_by_role("link", name="Payment summary", exact=True).click()
        self.heading("Payment summary")
        bank_row = self.page.get_by_role("row").filter(has_text="Bank 1")
        expect(bank_row).to_contain_text("10,000.00")
        expect(bank_row).to_contain_text("2,000.25")
        expect(self.page.get_by_label("Statement credits")).to_have_count(0)
        self.open_tools()
        self.page.get_by_role("link", name="Monthly reports", exact=True).click()
        self.heading("Monthly reports")
        self.page.locator("#year").fill("2025")
        self.page.get_by_role("button", name="View", exact=True).click()
        self.page.get_by_role("link", name="September 2025", exact=True).click()
        self.heading("September 2025")
        with self.page.expect_download() as result:
            self.page.get_by_role("link", name="Export month CSV").click()
        self.assertIn("10000.00", Path(result.value.path()).read_text(encoding="utf-8-sig"))
        self.page.get_by_role("link", name="Close month", exact=True).click()
        self.page.locator("#id_reason").fill("Checked September payments")
        self.page.get_by_role("checkbox").check()
        self.page.get_by_role("button", name="Close reviewed month").click()
        expect(self.page.get_by_text("Month closed.", exact=True)).to_be_visible()
        self.assertIsNotNone(MonthReview.objects.get().closed_at)
        self.money_form("income", "100")
        self.page.get_by_role("button", name="Save entry", exact=True).click()
        expect(self.page.get_by_text("September 2025 is closed.", exact=False)).to_be_visible()
        self.go("/?month=2025-09")
        self.page.get_by_role("link", name="Reopen month", exact=True).click()
        self.page.locator("#id_reason").fill("Reopen for correction")
        self.page.get_by_role("checkbox").check()
        self.page.get_by_role("button", name="Reopen month", exact=True).click()
        expect(self.page.get_by_text("Month reopened. Your reason was saved.", exact=True)).to_be_visible()
        self.assertIsNone(MonthReview.objects.get().closed_at)

    def test_responsive_navigation_and_login_form_no_overlap(self):
        add_stock(self.product, self.user, {"date": date(2025, 9, 1), "kind": "received", "quantity": 10})
        paths = ["/?month=2025-09", "/settings/", "/transactions/new/expense/", "/products/",
                 f"/products/{self.product.pk}/?month=2025-09", "/reports/?year=2025", "/payment-summary/"]
        for width in (1440, 390, 320):
            self.page.set_viewport_size({"width": width, "height": 950})
            for path in paths:
                self.go(path)
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), width + 1, (width, path))
                expect(self.page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
        self.page.get_by_role("button", name="Log out", exact=True).click()
        expect(self.page.get_by_label("Email")).to_be_visible()
        password = self.page.get_by_label(re.compile(r"^Password:?$")).bounding_box()
        button = self.page.get_by_role("button", name="Sign in", exact=True).bounding_box()
        self.assertGreaterEqual(button["y"], password["y"] + password["height"])

    def test_failed_save_preserves_form_and_retry_creates_one_record(self):
        self.money_form("expense", "4250")
        pending = []
        self.page.route("**/transactions/new/expense/**", lambda route: pending.append(route) if route.request.method == "POST" else route.continue_())
        self.page.get_by_role("button", name="Save entry", exact=True).click()
        expect(self.page.locator("#id_amount")).to_be_disabled()
        expect(self.page.locator("#id_account")).to_be_disabled()
        expect(self.page.get_by_role("button", name="Save entry", exact=True)).to_be_disabled()
        self.assertTrue(pending, "The save request should be pending")
        pending[0].abort()
        expect(self.page.locator("#request-error")).to_contain_text("could not confirm this save")
        expect(self.page.locator("#id_amount")).to_be_enabled()
        expect(self.page.locator("#id_account")).to_be_enabled()
        expect(self.page.locator("#id_amount")).to_have_value("4250")
        self.assertEqual(Entry.objects.count(), 0)
        self.page.unroute("**/transactions/new/expense/**")
        self.save_entry()
        self.assertEqual(Entry.objects.count(), 1)

    def test_theme_button_tab_and_sku_hover_behaviour(self):
        self.go("/?month=2025-09")
        self.assertEqual(self.page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor"),
                         "rgb(248, 246, 239)")
        for card in self.page.locator(".stat-card").all():
            self.assertEqual(card.evaluate("el => getComputedStyle(el).backgroundColor"), "rgb(255, 255, 255)")
            self.assertEqual(card.evaluate("el => getComputedStyle(el).color"), "rgb(32, 37, 34)")
        for name in ("Money received", "Expense"):
            button = self.page.get_by_role("link", name=re.compile(r"＋ " + name + r"$"))
            button.hover()
            expected = "rgb(237, 90, 84)" if name == "Expense" else "rgb(37, 100, 71)"
            self.assertEqual(button.evaluate("el => getComputedStyle(el).backgroundColor"), expected)
        tab = self.page.locator(".entry-tabs a").first
        tab.hover()
        self.assertEqual(tab.evaluate("el => getComputedStyle(el).backgroundColor"), "rgb(237, 245, 240)")
        favicon = self.page.locator('link[rel="icon"]').get_attribute("href")
        response = self.context.request.get(self.live_server_url + favicon)
        self.assertEqual(response.status, 200)
        self.assertIn("<svg", response.text())
        self.go("/products/?month=2025-09")
        link = self.page.locator(".product-card-link").first
        original = link.evaluate("el => getComputedStyle(el).backgroundColor")
        link.hover()
        self.assertEqual(link.evaluate("el => getComputedStyle(el).backgroundColor"), original)
        self.assertEqual(self.page.locator(".product-card").first.evaluate("el => getComputedStyle(el).backgroundColor"),
                         "rgb(255, 255, 255)")
        delete = self.page.locator(".product-card .danger-link").first
        delete.hover()
        self.assertEqual(delete.evaluate("el => getComputedStyle(el).backgroundColor"), "rgb(237, 90, 84)")
        delete.click()
        dialog = self.page.locator("#delete-dialog")
        confirmation = dialog.get_by_role("button", name="Delete SKU", exact=True)
        expect(confirmation).to_be_visible()
        confirmation.hover()
        self.assertEqual(confirmation.evaluate("el => getComputedStyle(el).backgroundColor"), "rgb(237, 90, 84)")
        dialog.get_by_role("link", name="Cancel", exact=True).click()
        expect(dialog).to_be_hidden()

    def test_compact_delete_modal_preserves_page_cancel_and_failed_retry(self):
        self.money_form("expense", "73.45")
        self.save_entry()
        original_url = self.page.url
        self.page.get_by_role("link", name="Delete", exact=True).first.click()
        dialog = self.page.locator("#delete-dialog")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("button", name="Delete entry", exact=True)).to_be_visible()
        self.assertEqual(self.page.url, original_url)
        self.assertLessEqual(dialog.bounding_box()["width"], 361)
        dialog.get_by_role("link", name="Cancel", exact=True).click()
        expect(dialog).to_be_hidden()
        self.assertEqual(Entry.objects.filter(voided_at__isnull=True).count(), 1)
        self.page.get_by_role("link", name="Delete", exact=True).first.click()
        delete_path = re.compile(r"/transactions/\d+/delete/")
        self.page.route(delete_path, lambda route: route.abort() if route.request.method == "POST" else route.continue_())
        dialog.get_by_role("button", name="Delete entry", exact=True).click()
        expect(dialog.locator("#request-error")).to_contain_text("could not confirm this delete")
        self.assertEqual(Entry.objects.filter(voided_at__isnull=True).count(), 1)
        expect(dialog.get_by_role("button", name="Delete entry", exact=True)).to_be_enabled()
        self.page.unroute(delete_path)
        dialog.get_by_role("button", name="Delete entry", exact=True).click()
        expect(dialog).to_be_hidden()
        self.heading("September 2025")
        self.assertEqual(Entry.objects.filter(voided_at__isnull=True).count(), 0)

    def test_search_month_filters_back_and_logout(self):
        self.money_form("income", "300")
        self.page.get_by_text("Optional details", exact=True).click()
        self.page.get_by_label("Statement reference (optional)").fill("QA-SEARCH")
        self.save_entry()
        self.page.get_by_label("Search entries").fill("QA-SEARCH")
        self.page.get_by_role("button", name="Search", exact=True).click()
        expect(self.page).to_have_url(re.compile(r"q=QA-SEARCH"))
        expect(self.page.get_by_text("QA-SEARCH", exact=True)).to_be_visible()
        self.page.locator(".entry-tabs").get_by_role("link", name="Expenses", exact=True).click()
        expect(self.page.get_by_text("No entries", exact=True)).to_be_visible()
        self.page.locator(".entry-tabs").get_by_role("link", name="All", exact=True).click()
        expect(self.page).to_have_url(re.compile(r"kind=all"))
        pending = []
        self.page.route("**/?month=2025-08*", lambda route: pending.append(route))
        self.page.get_by_label("Review month").fill("2025-08")
        self.page.get_by_role("button", name="View", exact=True).click()
        expect(self.page.get_by_label("Review month")).to_be_disabled()
        self.assertTrue(pending, "The month navigation should be pending")
        pending[0].continue_()
        self.heading("August 2025")
        expect(self.page.get_by_label("Review month")).to_be_enabled()
        self.page.unroute("**/?month=2025-08*")
        self.page.go_back()
        self.heading("September 2025")
        self.page.get_by_role("button", name="Log out", exact=True).click()
        expect(self.page.get_by_label("Email")).to_be_visible()

    def test_email_login_and_password_reset(self):
        from django.core import mail
        self.page.get_by_role("button", name="Log out", exact=True).click()
        self.page.get_by_role("link", name="Forgot your password?").click()
        self.page.get_by_label("Email").fill("tester@example.test")
        self.page.get_by_role("button", name="Send reset link").click()
        self.heading("Check your email")
        self.assertEqual(len(mail.outbox), 1)
        self.page.goto(re.search(r"http://\S+", mail.outbox[0].body).group())
        self.page.locator('input[name="new_password1"]').fill("ChangedOnly!2026")
        self.page.locator('input[name="new_password2"]').fill("ChangedOnly!2026")
        self.page.get_by_role("button", name="Save password").click()
        self.heading("Password updated")
        self.page.get_by_role("link", name="Sign in", exact=True).click()
        self.page.get_by_label("Email").fill("TESTER@example.test")
        self.page.get_by_label(re.compile(r"^Password:?$")).fill("ChangedOnly!2026")
        self.page.get_by_role("button", name="Sign in", exact=True).click()
        self.heading("Entries")

    def test_forms_work_without_javascript(self):
        self.context.close()
        self.context = self.browser.new_context(java_script_enabled=False)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.login()
        self.money_form("expense", "50.01")
        self.page.get_by_text("Add a category", exact=True).click()
        self.page.locator("#id_category-name").fill("No JS category")
        self.page.get_by_role("button", name="Create and select category").click()
        expect(self.page.locator("#id_category option:checked")).to_have_text("No JS category")
        self.save_entry()
        self.assertEqual(Entry.objects.count(), 1)

    @override_settings(PASSWORD_RESET_ENABLED=False)
    def test_demo_login_without_password_recovery(self):
        self.page.get_by_role("button", name="Log out", exact=True).click()
        expect(self.page.get_by_role("link", name="Forgot your password?")).to_have_count(0)
        self.login()
