"""Run explicitly: manage.py test tracker.browser_tests --settings=config.browser_settings --keepdb.

Uses an isolated Django test database and headless Edge (or PLAYWRIGHT_CHANNEL).
Screenshots go to the OS temporary directory, never the client database/repository.
"""
import os
from pathlib import Path
from datetime import date
from decimal import Decimal
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright, expect

from tracker.models import Account, Category, Entry, Product, StockMovement, BankTally, MonthReview
from tracker.services import setup_defaults, add_stock


@override_settings(DEBUG=True, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class BrowserWorkflows(StaticLiveServerTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("browser_tester", "tester@example.test", "BrowserOnly!2026")
        setup_defaults(self.user)
        self.bank = Account.objects.get(owner=self.user, name="Bank 1")
        self.category = Category.objects.get(owner=self.user, name="General")
        self.product = Product.objects.create(owner=self.user, sku="QA-BAG", name="Sample bag")
        # Playwright's sync API owns an event loop in this test thread. Only this
        # isolated test process permits synchronous ORM assertions in that thread.
        self.async_patch = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        self.async_patch.start()
        self.addCleanup(self.async_patch.stop)
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL", "msedge"))
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("response", self.record_error_response)
        self.login()

    def record_error_response(self, response):
        if response.status >= 400 and not response.url.endswith("/favicon.ico"):
            self.errors.append(f"HTTP {response.status}: {response.url}")
            folder = Path(tempfile.gettempdir()) / "profit-tracker-ui-review"
            folder.mkdir(exist_ok=True)
            (folder / "http-error.html").write_text(response.text(), encoding="utf-8")
            print(f"Browser HTTP error: {response.status} {response.url}")

    def tearDown(self):
        folder = Path(tempfile.gettempdir()) / "profit-tracker-ui-review"
        folder.mkdir(exist_ok=True)
        self.page.screenshot(path=str(folder / f"{self._testMethodName}.png"), full_page=True)
        self.assertEqual(self.errors, [], "Browser JavaScript errors")

    def login(self):
        self.page.goto(self.live_server_url + "/login/")
        self.page.get_by_label("Email").fill("tester@example.test")
        self.page.get_by_label("Password").fill("BrowserOnly!2026")
        self.page.get_by_role("button", name="Sign in", exact=True).click()
        expect(self.page.get_by_role("heading", name="Source breakdown")).to_be_visible()

    def go(self, path):
        self.page.goto(self.live_server_url + path)

    def heading(self, name):
        expect(self.page.get_by_role("heading", name=name, exact=True)).to_be_visible()

    def money_form(self, kind, amount="1000"):
        self.go(f"/transactions/new/{kind}/?month=2025-09")
        self.page.locator("#id_date").fill("2025-09-12")
        self.page.locator("#id_amount").fill(amount)
        self.page.locator("#id_account").select_option(str(self.bank.pk))
        if kind == "income":
            self.page.locator("#id_source").select_option("razorpay")
        elif kind == "expense":
            self.page.locator("#id_category").select_option(str(self.category.pk))

    def save_entry(self):
        self.page.get_by_role("button", name="Save entry", exact=True).click()
        self.heading("September 2025")
        expect(self.page.get_by_text("Entry saved.", exact=True)).to_be_visible()

    def test_inline_creation_edit_void_and_save_another(self):
        self.go("/transactions/new/expense/?month=2025-09")
        expect(self.page.locator("[data-paid-by]")).to_be_hidden()
        self.assertNotIn("---------", self.page.locator("#id_category").inner_text())
        self.page.locator("#id_amount").fill("4250")
        self.page.get_by_text("Add a category", exact=True).click()
        self.page.locator("#id_category-name").fill("Browser packaging")
        self.page.get_by_role("button", name="Create and select category").click()
        expect(self.page.get_by_text("Browser packaging added and selected. Your entry is still unsaved.")).to_be_visible()
        expect(self.page.locator("#id_amount")).to_have_value("4250")
        self.assertEqual(Entry.objects.count(), 0)
        self.page.get_by_text("Add a payment account", exact=True).click()
        self.page.locator("#id_account-name").fill("Browser wallet")
        self.page.locator("#id_account-kind").select_option("wallet")
        self.page.get_by_role("button", name="Create and select account").click()
        expect(self.page.locator("#id_account option:checked")).to_have_text("Browser wallet")
        self.page.locator("#id_date").fill("2025-09-12")
        self.page.get_by_role("button", name="Save & add another").click()
        expect(self.page.get_by_text("Entry saved.", exact=True)).to_be_visible()
        expect(self.page.locator("#id_amount")).to_have_value("")
        self.page.locator("#id_date").fill("2025-09-13")
        self.page.locator("#id_amount").fill("250")
        self.save_entry()
        self.assertEqual(Entry.objects.count(), 2)
        self.page.get_by_role("link", name="Edit", exact=True).first.click()
        expect(self.page.locator("#id_amount")).to_have_value("250.00")
        self.page.locator("#id_amount").fill("200")
        self.page.get_by_label("Reason for correction").fill("Corrected receipt")
        self.save_entry()
        self.page.get_by_role("link", name="Edit", exact=True).first.click()
        self.page.get_by_role("link", name="Void entry").click()
        self.page.get_by_role("link", name="Cancel", exact=True).click()
        expect(self.page.get_by_label("Reason for correction")).to_be_visible()
        self.page.get_by_role("link", name="Void entry").click()
        self.page.locator("#id_reason").fill("Duplicate receipt")
        self.page.get_by_role("checkbox").check()
        self.page.get_by_role("button", name="Confirm void").click()
        expect(self.page.get_by_text("Entry voided;", exact=False)).to_be_visible()
        self.assertEqual(Entry.objects.filter(voided_at__isnull=True).count(), 1)

    def test_stock_product_actions_and_negative_stock(self):
        self.go("/products/?month=2025-09")
        self.page.get_by_role("link", name="＋ Add SKU").click()
        self.page.get_by_label("SKU / design code").fill("QA-NEW")
        self.page.locator("#id_name").fill("New test bag")
        self.page.get_by_role("button", name="Save SKU", exact=True).click()
        self.heading("New test bag")
        self.page.get_by_role("link", name="＋ Receive stock").click()
        self.page.locator("#id_date").fill("2025-09-01")
        self.page.get_by_label("Quantity").fill("10")
        self.page.locator("#id_payment_date").fill("2025-09-01")
        self.page.locator("#id_manufacturing_cost").fill("5000")
        self.page.locator("#id_base_shipping_cost").fill("1000")
        self.page.locator("#id_payment_account").select_option(str(self.bank.pk))
        self.page.get_by_label("I have entered the full landed cost (use zero for any cost that does not apply).", exact=False).check()
        self.page.get_by_role("button", name="Receive stock", exact=True).click()
        self.heading("New test bag")
        self.page.get_by_role("link", name="＋ Record units sold").click()
        self.page.locator("#id_date").fill("2025-09-12")
        self.page.get_by_label("Quantity").fill("11")
        self.page.get_by_role("button", name="Record units sold", exact=True).click()
        expect(self.page.get_by_text("This would make stock negative.", exact=False)).to_be_visible()
        self.page.get_by_label("Quantity").fill("3")
        self.page.get_by_role("button", name="Record units sold", exact=True).click()
        self.heading("New test bag")
        self.assertEqual(Entry.objects.count(), 2)
        self.page.get_by_role("link", name="Reverse mistake").first.click()
        self.page.locator("#id_reason").fill("Wrong sale quantity")
        self.page.get_by_role("checkbox").check()
        self.page.get_by_role("button", name="Reverse movement").click()
        expect(self.page.get_by_text("Reversed · excluded from totals")).to_be_visible()
        self.page.get_by_text("More stock actions", exact=True).click()
        self.page.get_by_role("link", name="Returns, damage, opening stock or adjustment").click()
        self.page.locator("#id_date").fill("2025-09-14")
        self.page.locator("#id_kind").select_option("damaged")
        self.page.get_by_label("Quantity").fill("1")
        self.page.get_by_role("button", name="Save stock movement").click()
        self.heading("New test bag")
        self.page.get_by_role("link", name="Edit SKU details").click()
        self.page.locator("#id_name").fill("Updated test bag")
        self.page.get_by_role("button", name="Save SKU", exact=True).click()
        self.heading("Updated test bag")

    def test_reports_bank_tally_export_close_and_reopen(self):
        self.money_form("income", "10000")
        self.save_entry()
        self.money_form("expense", "2000")
        self.save_entry()
        self.money_form("withdrawal", "1000")
        self.save_entry()
        self.money_form("transfer", "500")
        self.page.locator("#id_notes").fill("Transfer to reserve")
        self.page.locator("#id_destination").select_option(str(Account.objects.get(owner=self.user, name="Bank 2").pk))
        self.save_entry()
        self.page.locator(".sidebar-tools").get_by_role("link", name="Payment checks", exact=True).click()
        self.heading("Payment checks")
        self.page.get_by_label("Statement credits").fill("10000")
        self.page.get_by_label("Statement debits").fill("3500")
        self.page.get_by_role("button", name="Save statement totals").click()
        expect(self.page.get_by_text("Statement totals saved.", exact=False)).to_be_visible()
        self.assertEqual(BankTally.objects.count(), 1)
        self.page.locator(".sidebar-tools").get_by_role("link", name="Monthly reports").click()
        self.heading("Monthly reports")
        self.page.locator("#year").fill("2025")
        self.page.get_by_role("button", name="View", exact=True).click()
        self.page.get_by_role("link", name="September 2025", exact=True).click()
        self.heading("September 2025")
        self.page.get_by_text("More actions", exact=True).click()
        with self.page.expect_download() as result:
            self.page.get_by_role("link", name="Export this month").click()
        self.assertEqual(result.value.suggested_filename, "transactions-2025-09.csv")
        self.assertIn("10000.00", Path(result.value.path()).read_text(encoding="utf-8-sig"))
        self.page.locator(".sidebar-tools").get_by_role("link", name="Month review").click()
        self.page.locator("#id_reason").fill("Checked September statements")
        self.page.get_by_role("checkbox").check()
        self.page.get_by_role("button", name="Close reviewed month").click()
        expect(self.page.get_by_role("button", name="Reopen month")).to_be_visible()
        self.assertIsNotNone(MonthReview.objects.get().closed_at)
        self.money_form("income", "100")
        self.page.get_by_role("button", name="Save entry", exact=True).click()
        expect(self.page.get_by_text("September 2025 is closed.", exact=False)).to_be_visible()
        self.page.locator(".sidebar-tools").get_by_role("link", name="Month review").click()
        self.page.locator("#id_reason").fill("Reopen for correction")
        self.page.get_by_role("checkbox").check()
        self.page.get_by_role("button", name="Reopen month", exact=True).click()
        expect(self.page.get_by_role("button", name="Close reviewed month")).to_be_visible()
        self.page.get_by_role("link", name="Change history", exact=True).click()
        self.heading("Change history")
        self.page.get_by_text("Show details", exact=True).first.click()
        expect(self.page.locator(".audit-details").first).to_be_visible()

    def test_responsive_pages_navigation_and_logout(self):
        add_stock(self.product, self.user, {
            "date": date(2025, 9, 1), "kind": "received", "quantity": 10,
            "manufacturing_cost": Decimal("5000.00"), "base_shipping_cost": Decimal("500.00"),
            "extra_shipping_cost": Decimal("20.25"), "other_direct_cost": Decimal("10.50"),
            "batch_name": "September demo lot", "payment_account": self.bank, "costs_confirmed": True,
        })
        add_stock(self.product, self.user, {"date": date(2025, 9, 10), "kind": "sold", "quantity": 4})
        Entry.objects.create(owner=self.user, kind="income", date=date(2025, 9, 12),
            sale_date=date(2025, 9, 10), recognized_amount=Decimal("5000.00"),
            amount=Decimal("5000.00"), source="upi", account=self.bank)
        artifact_dir = Path(tempfile.gettempdir()) / "profit-tracker-ui-review"
        artifact_dir.mkdir(exist_ok=True)
        paths = ["/?month=2025-09", "/settings/", "/transactions/new/expense/", "/products/",
                 f"/products/{self.product.pk}/?month=2025-09", "/reports/?year=2025", "/bank-tally/", "/month-review/", "/history/", reverse("stock_add", args=[self.product.pk]) + "?action=received"]
        for width in (1440, 390, 320):
            self.page.set_viewport_size({"width": width, "height": 950})
            for index, path in enumerate(paths):
                self.go(path)
                self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), width + 1, (width, path))
                expect(self.page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
                if index in (0, 1, 2, 4, 10):
                    self.page.screenshot(path=str(artifact_dir / f"{width}-{index}.png"), full_page=True)
            self.go("/?month=2025-09")
            self.page.get_by_text("More actions", exact=True).click()
            expect(self.page.get_by_role("link", name="Record transfer or repayment")).to_be_visible()
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), width + 1)
            self.page.keyboard.press("Escape")
            expect(self.page.get_by_role("link", name="Record transfer or repayment")).to_be_hidden()
        self.page.get_by_role("link", name="Settings", exact=False).first.click()
        self.heading("Accounts & categories")
        self.page.get_by_role("navigation", name="Main navigation").get_by_role("link", name="Monthly tracker", exact=False).click()
        self.heading("September 2025")
        self.page.get_by_role("button", name="Log out", exact=True).click()
        expect(self.page.get_by_label("Email")).to_be_visible()
        print(f"Browser screenshots: {artifact_dir}")

    def test_failed_save_keeps_form_and_can_retry(self):
        self.money_form("expense", "4250")
        self.page.route("**/transactions/new/expense/**", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
        self.page.get_by_role("button", name="Save entry", exact=True).click()
        expect(self.page.locator("#request-error")).to_contain_text("could not confirm this save")
        expect(self.page.locator("#id_amount")).to_have_value("4250")
        self.assertEqual(Entry.objects.count(), 0)
        self.page.unroute("**/transactions/new/expense/**")
        self.save_entry()
        self.assertEqual(Entry.objects.count(), 1)

    def test_settings_search_and_month_filters(self):
        self.go("/settings/?month=2025-09")
        self.page.get_by_role("button", name="Add starter accounts & categories").click()
        expect(self.page.get_by_text("Default accounts and categories added.", exact=False)).to_be_visible()
        self.assertEqual(Account.objects.count(), 7)
        self.page.locator("#id_account-name").fill("New bank")
        self.page.get_by_role("button", name="Add account", exact=True).click()
        expect(self.page.get_by_text("New bank", exact=True)).to_be_visible()
        self.page.locator("#id_category-name").fill("Photography")
        self.page.get_by_role("button", name="Add category", exact=True).click()
        expect(self.page.get_by_text("Photography", exact=True)).to_be_visible()
        self.money_form("income", "300")
        self.page.get_by_text("Optional details", exact=True).click()
        self.page.get_by_label("Statement reference (optional)").fill("QA-SEARCH")
        self.save_entry()
        self.page.get_by_label("Search entries").fill("QA-SEARCH")
        self.page.get_by_role("button", name="Search", exact=True).click()
        expect(self.page.get_by_text("QA-SEARCH", exact=True)).to_be_visible()
        self.page.get_by_role("link", name="Expenses", exact=True).click()
        expect(self.page.get_by_text("No entries to show.", exact=False)).to_be_visible()
        self.page.get_by_role("link", name="All", exact=True).click()
        expect(self.page.get_by_text("QA-SEARCH", exact=True)).to_be_visible()
        self.page.get_by_label("Review month").fill("2025-08")
        self.page.get_by_role("button", name="View", exact=True).click()
        self.heading("August 2025")
        self.page.go_back()
        self.heading("September 2025")

    def test_email_login_logout_and_password_reset(self):
        import re
        from django.core import mail

        self.page.get_by_role("button", name="Log out", exact=True).click()
        expect(self.page.get_by_label("Email")).to_be_visible()
        self.login()
        expect(self.page.locator(".sidebar")).to_be_visible()
        self.page.get_by_role("button", name="Log out", exact=True).click()
        self.page.get_by_role("link", name="Forgot your password?").click()
        self.page.get_by_label("Email").fill("tester@example.test")
        self.page.get_by_role("button", name="Send reset link").click()
        self.heading("Check your email")
        self.assertEqual(len(mail.outbox), 1)
        reset_url = re.search(r"http://\S+", mail.outbox[0].body).group()
        self.page.goto(reset_url)
        self.page.locator('input[name="new_password1"]').fill("ChangedOnly!2026")
        self.page.locator('input[name="new_password2"]').fill("ChangedOnly!2026")
        self.page.get_by_role("button", name="Save password").click()
        self.heading("Password updated")
        self.page.get_by_role("link", name="Sign in", exact=True).click()
        self.page.get_by_label("Email").fill("TESTER@example.test")
        self.page.get_by_label("Password").fill("ChangedOnly!2026")
        self.page.get_by_role("button", name="Sign in", exact=True).click()
        expect(self.page.locator(".sidebar")).to_be_visible()

    @override_settings(PASSWORD_RESET_ENABLED=False)
    def test_demo_email_login_without_recovery(self):
        self.page.get_by_role("button", name="Log out", exact=True).click()
        expect(self.page.get_by_label("Email")).to_be_visible()
        expect(self.page.get_by_role("link", name="Forgot your password?")).to_have_count(0)
        for width in (1440, 390, 320):
            self.page.set_viewport_size({"width": width, "height": 900})
            self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        self.login()
        expect(self.page.locator(".sidebar")).to_be_visible()

    def test_forms_work_without_javascript(self):
        self.context.close()
        self.context = self.browser.new_context(java_script_enabled=False)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.login()
        self.go("/transactions/new/expense/?month=2025-09")
        self.page.get_by_text("Add a category", exact=True).click()
        self.page.locator("#id_category-name").fill("No JS category")
        self.page.get_by_role("button", name="Create and select category").click()
        expect(self.page.locator("#id_category option:checked")).to_have_text("No JS category")
        self.page.locator("#id_date").fill("2025-09-12")
        self.page.locator("#id_amount").fill("50")
        self.save_entry()
        self.assertEqual(Entry.objects.count(), 1)
