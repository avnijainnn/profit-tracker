from datetime import date, timedelta
from decimal import Decimal
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from tracker.forms import EntryForm
from tracker.models import Account, BankTally, Category, ChangeLog, Entry, MonthReview, Product, StockMovement, InventoryLot, LotDepletion
from tracker.services import add_stock, bank_activity, product_stats, report, setup_defaults


class WorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("tanvi_test", password="test-only-password")
        self.other = get_user_model().objects.create_user("other_test", password="test-only-password")
        setup_defaults(self.user)
        self.bank = Account.objects.get(owner=self.user, name="Bank 1")
        self.category = Category.objects.get(owner=self.user, name="Manufacturing")
        self.product = Product.objects.create(owner=self.user, sku="AQUA", name="Aqua Babe")
        self.client.force_login(self.user)

    def entry_data(self, **overrides):
        data = {"date": "2025-08-22", "amount": "35000.00", "account": self.bank.pk,
                "category": self.category.pk, "product": self.product.pk, "paid_by": "", "reference": "", "notes": "Advance",
                "submission_token": str(uuid.uuid4()), "expected_revision": 0}
        data.update(overrides)
        return data

    def test_advance_and_next_month_stock_count_once(self):
        response = self.client.post(reverse("entry_add", args=["expense"]), self.entry_data())
        self.assertEqual(response.status_code, 302)
        self.client.post(reverse("stock_add", args=[self.product.pk]), {"date": "2025-09-03", "kind": "received", "quantity": 50, "batch_name": "Sep batch", "notes": "", "costs_confirmed": "on", "submission_token": str(uuid.uuid4())})
        august = report(self.user, date(2025, 8, 1), date(2025, 9, 1))
        september = report(self.user, date(2025, 9, 1), date(2025, 10, 1))
        self.assertEqual(august["totals"]["expense"], Decimal("35000"))
        self.assertEqual(september["totals"]["expense"], Decimal("0"))
        self.assertEqual(Entry.objects.count(), 1)
        stats = product_stats(self.product, date(2025, 8, 1), date(2025, 9, 1))
        self.assertEqual(stats["available"], 50)
        self.assertEqual(stats["stock_at_month_end"], 0)
        self.assertEqual(stats["spent"], Decimal("35000"))

    def test_income_entries_cumulative(self):
        for amount in ("10000", "15000"):
            self.client.post(reverse("entry_add", args=["income"]), {"date": "2025-09-05", "amount": amount, "account": self.bank.pk, "source": "razorpay", "submission_token": str(uuid.uuid4()), "expected_revision": 0})
        data = report(self.user, date(2025, 9, 1), date(2025, 10, 1))
        self.assertEqual(data["totals"]["income"], Decimal("25000"))
        self.assertEqual(data["sources"], [("Razorpay settlement", Decimal("25000"))])

    def test_fifo_landed_cost_and_cash_vs_sale_months(self):
        def receive(day, qty, cost, token):
            return add_stock(self.product, self.user, {
                "date": date(2025, 9, day), "payment_date": date(2025, 9, day),
                "kind": "received", "quantity": qty, "batch_name": f"Lot {day}",
                "manufacturing_cost": Decimal(cost), "base_shipping_cost": Decimal("200.00"),
                "extra_shipping_cost": Decimal("0.00"), "other_direct_cost": Decimal("0.00"),
                "payment_account": self.bank, "costs_confirmed": True, "submission_token": token,
            })
        receive(1, 4, "1000.00", uuid.uuid4())
        receive(5, 4, "1600.00", uuid.uuid4())
        add_stock(self.product, self.user, {"date": date(2025, 9, 6), "kind": "sold", "quantity": 6,
                                            "submission_token": uuid.uuid4()})
        self.client.post(reverse("entry_add", args=["income"]), {
            "date": "2025-10-02", "sale_date": "2025-09-06", "recognized_amount": "4000.00", "amount": "3600.00",
            "account": self.bank.pk, "source": "razorpay", "submission_token": str(uuid.uuid4()),
            "expected_revision": 0,
        })
        depletion = list(LotDepletion.objects.select_related("lot").order_by("lot__received_date"))
        self.assertEqual([(d.lot.batch_name, d.quantity, d.unit_cost) for d in depletion], [
            ("Lot 1", 4, Decimal("300.000000")), ("Lot 5", 2, Decimal("450.000000"))])
        sep = report(self.user, date(2025, 9, 1), date(2025, 10, 1))["totals"]
        oct_data = report(self.user, date(2025, 10, 1), date(2025, 11, 1))["totals"]
        self.assertEqual(sep["cash_profit"], Decimal("-3000.00"))
        self.assertEqual(sep["operating_income"], Decimal("4000.00"))
        self.assertEqual(sep["cogs"], Decimal("2100.00"))
        self.assertEqual(sep["operating_profit"], Decimal("1900.00"))
        self.assertEqual(oct_data["cash_profit"], Decimal("3600.00"))
        self.assertEqual(oct_data["operating_income"], Decimal("0.00"))

    def test_link_existing_advance_to_lot_without_duplicate_cash_expense(self):
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(
            date="2025-08-22", amount="1200.00", notes="Manufacturing advance"))
        advance = Entry.objects.get()
        lot_movement = add_stock(self.product, self.user, {
            "date": date(2025, 9, 3), "kind": "received", "quantity": 10,
            "existing_cost_entries": [advance], "costs_confirmed": True,
            "submission_token": uuid.uuid4(),
        })
        advance.refresh_from_db()
        self.assertTrue(advance.capitalized_inventory_cost)
        self.assertEqual(advance.inventory_lot.manufacturing_cost, Decimal("1200.00"))
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(product_stats(self.product, date(2025, 8, 1), date(2025, 9, 1))["spent"], Decimal("1200.00"))
        self.assertEqual(report(self.user, date(2025, 8, 1), date(2025, 9, 1))["totals"]["cash_profit"], Decimal("-1200.00"))
        add_stock(self.product, self.user, {"date": date(2025, 9, 10), "kind": "sold", "quantity": 4,
                                            "submission_token": uuid.uuid4()})
        september = report(self.user, date(2025, 9, 1), date(2025, 10, 1))["totals"]
        self.assertEqual(september["cogs"], Decimal("480.00"))
        self.assertEqual(lot_movement.inventory_lot.costs_confirmed, True)

    def test_closed_sale_month_protects_later_cash_receipt_void(self):
        self.client.post(reverse("entry_add", args=["income"]), {
            "date": "2025-10-02", "sale_date": "2025-09-20", "recognized_amount": "500.00",
            "amount": "450.00", "account": self.bank.pk, "source": "razorpay",
            "submission_token": str(uuid.uuid4()), "expected_revision": 0,
        })
        income = Entry.objects.get(kind=Entry.Kind.INCOME)
        MonthReview.objects.create(owner=self.user, month=date(2025, 9, 1), closed_at=timezone.now())
        response = self.client.post(reverse("entry_void", args=[income.pk]), {
            "reason": "Correction requested", "expected_revision": income.revision,
            "submission_token": str(uuid.uuid4()), "confirm": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "September 2025 is closed")
        income.refresh_from_db()
        self.assertIsNone(income.voided_at)

    def test_edit_get_preserves_actual_date(self):
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data())
        entry = Entry.objects.get()
        response = self.client.get(reverse("entry_edit", args=[entry.pk]), {"month": "2025-10"})
        self.assertContains(response, 'value="2025-08-22"')

    def test_edit_and_void_audited(self):
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data())
        entry = Entry.objects.get()
        self.client.post(reverse("entry_edit", args=[entry.pk]), self.entry_data(amount="34000", expected_revision=1, change_reason="Corrected statement amount"))
        self.assertTrue(ChangeLog.objects.filter(action="entry_updated").exists())
        self.client.post(reverse("entry_void", args=[entry.pk]), {"reason": "Duplicate entry discovered", "expected_revision": 2, "submission_token": str(uuid.uuid4()), "confirm": "on"})
        entry.refresh_from_db()
        self.assertIsNotNone(entry.voided_at)
        self.assertEqual(report(self.user, date(2025, 8, 1), date(2025, 9, 1))["totals"]["expense"], 0)

    def test_reference_duplicate_blocked(self):
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(reference="unique-bank-id"))
        response = self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(reference="unique-bank-id"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(Entry.objects.count(), 1)

    def test_future_date_negative_amount_and_missing_category_rejected(self):
        for overrides in ({"date": str(timezone.localdate() + timedelta(days=1))}, {"amount": "-1"}, {"amount": "0"}, {"category": ""}):
            with self.subTest(overrides=overrides):
                self.assertFalse(EntryForm(self.entry_data(**overrides), owner=self.user, kind="expense").is_valid())

    def test_paid_by_required_and_highlighted(self):
        account = Account.objects.get(owner=self.user, name="Paid by someone else")
        form = EntryForm(self.entry_data(account=account.pk), owner=self.user, kind="expense")
        self.assertFalse(form.is_valid())
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(account=account.pk, paid_by="Helper"))
        data = report(self.user, date(2025, 8, 1), date(2025, 9, 1))
        self.assertEqual(data["third_party"], Decimal("35000"))
        self.assertEqual(data["totals"]["cash_profit"], Decimal("0.00"))

    def test_other_workspace_foreign_keys_rejected(self):
        foreign_account = Account.objects.create(owner=self.other, name="Other private bank")
        form = EntryForm(self.entry_data(account=foreign_account.pk), owner=self.user, kind="expense")
        self.assertFalse(form.is_valid())

    def test_record_urls_and_csv_are_owner_scoped(self):
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(reference="PRIVATE-REF"))
        entry = Entry.objects.get()
        self.client.force_login(self.other)
        for route, pk in (("entry_edit", entry.pk), ("entry_void", entry.pk), ("product_detail", self.product.pk), ("stock_add", self.product.pk)):
            self.assertEqual(self.client.get(reverse(route, args=[pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("export_csv"), {"month": "2025-08"}), "PRIVATE-REF")

    def test_backdated_stock_cannot_make_past_negative(self):
        add_stock(self.product, self.user, {"date": date(2025, 9, 4), "kind": "received", "quantity": 10})
        with self.assertRaises(ValidationError):
            add_stock(self.product, self.user, {"date": date(2025, 9, 3), "kind": "sold", "quantity": 1})
        with self.assertRaises(ValidationError):
            add_stock(self.product, self.user, {"date": date(2025, 9, 5), "kind": "sold", "quantity": 11})

    def test_all_main_pages_render(self):
        routes = [("dashboard", []), ("bank_tally", []), ("monthly_reports", []), ("products", []), ("product_detail", [self.product.pk]),
                  ("product_add", []), ("product_edit", [self.product.pk]), ("stock_add", [self.product.pk]),
                  ("entry_add", ["income"]), ("entry_add", ["expense"]), ("entry_add", ["withdrawal"]),
                  ("entry_add", ["transfer"]), ("settings", []), ("history", [])]
        for name, args in routes:
            with self.subTest(name=name, args=args):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_shared_shell_uses_dark_color_scheme_and_versioned_stylesheet(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, '<meta name="color-scheme" content="dark">')
        self.assertContains(response, "tracker/app.css?v=3")

    def test_dashboard_tabs_and_search_filter_monthly_entries(self):
        self.client.post(reverse("entry_add", args=["income"]), {
            "date": "2025-08-22", "amount": "1000", "account": self.bank.pk,
            "source": "razorpay", "reference": "SALE-REF", "submission_token": str(uuid.uuid4()),
            "expected_revision": 0,
        })
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(reference="ADVANCE-REF"))
        response = self.client.get(reverse("dashboard"), {"month": "2025-08", "kind": "expense", "q": "ADVANCE-REF"})
        self.assertContains(response, "ADVANCE-REF")
        self.assertNotContains(response, "SALE-REF")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, 'id="entries"')
        self.assertContains(response, "kind=income")
        self.assertContains(response, "kind=all")
        self.assertContains(response, "#entries")
        self.assertContains(response, 'action="#entries"')

    def test_entry_form_exposes_inline_labels_and_optional_details(self):
        response = self.client.get(reverse("entry_add", args=["expense"]), {"month": "2025-08", "product": self.product.pk})
        self.assertContains(response, "Add a category")
        self.assertContains(response, "Add a payment account")
        self.assertContains(response, "Optional details")
        self.assertContains(response, f'<option value="{self.product.pk}" selected')

    def test_product_detail_has_separate_stock_actions_and_prefills_expense(self):
        response = self.client.get(reverse("product_detail", args=[self.product.pk]), {"month": "2025-08"})
        self.assertContains(response, "action=received")
        self.assertContains(response, "action=sold")
        self.assertContains(response, f"product={self.product.pk}")

    def test_more_stock_actions_exclude_receive_and_sale(self):
        response = self.client.get(reverse("stock_add", args=[self.product.pk]), {"action": "more"})
        self.assertContains(response, "Saleable return")
        self.assertContains(response, "Opening stock / adjustment in")
        self.assertNotContains(response, "Stock received / new batch")
        self.assertNotContains(response, "Units sold")

    def test_units_sold_feed_fifo_cogs_not_money_in(self):
        add_stock(self.product, self.user, {"date": date(2025, 8, 1), "kind": "received", "quantity": 5,
                                            "submission_token": uuid.uuid4()})
        add_stock(self.product, self.user, {"date": date(2025, 8, 12), "kind": "sold", "quantity": 2,
                                            "submission_token": uuid.uuid4()})
        stats = product_stats(self.product, date(2025, 8, 1), date(2025, 9, 1))
        totals = report(self.user, date(2025, 8, 1), date(2025, 9, 1))["totals"]
        self.assertEqual(stats["month_cogs"], Decimal("0.00"))
        self.assertEqual(totals["income"], Decimal("0.00"))
        self.assertEqual(totals["result"], Decimal("0.00"))

    def test_sold_stock_form_tracks_units_only(self):
        add_stock(self.product, self.user, {"date": date(2025, 8, 1), "kind": "received", "quantity": 5,
                                            "submission_token": uuid.uuid4()})
        sale_url = f"{reverse('stock_add', args=[self.product.pk])}?month=2025-08&action=sold"
        form_response = self.client.get(sale_url)
        self.assertNotContains(form_response, "SKU sales total")
        response = self.client.post(sale_url, {
            "date": "2025-08-12", "kind": "sold", "quantity": "2",
            "notes": "", "submission_token": str(uuid.uuid4()),
        })
        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.get(kind="sold")
        self.assertIsNone(movement.sales_amount)
        self.assertEqual(report(self.user, date(2025, 8, 1), date(2025, 9, 1))["totals"]["income"], Decimal("0.00"))

    def test_bank_tally_compares_month_totals_and_is_replay_safe(self):
        self.client.post(reverse("entry_add", args=["income"]), {
            "date": "2025-08-22", "sale_date": "2025-08-20", "recognized_amount": "10000.00", "amount": "10000.00", "account": self.bank.pk,
            "source": "razorpay", "submission_token": str(uuid.uuid4()), "expected_revision": 0,
        })
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(amount="3500.00"))
        second_bank = Account.objects.get(owner=self.user, name="Bank 2")
        self.client.post(reverse("entry_add", args=["transfer"]), {
            "date": "2025-08-24", "amount": "200.00", "account": self.bank.pk,
            "destination": second_bank.pk, "notes": "Move to reserve",
            "submission_token": str(uuid.uuid4()), "expected_revision": 0,
        })
        payload = {
            "account": self.bank.pk, "statement_credits": "10000.00", "statement_debits": "3700.00",
            "notes": "August statement", "submission_token": str(uuid.uuid4()), "expected_revision": 0,
        }
        tally_url = f"{reverse('bank_tally')}?month=2025-08&account={self.bank.pk}"
        response = self.client.post(tally_url, payload)
        self.assertEqual(response.status_code, 302)
        self.client.post(tally_url, payload)
        self.assertEqual(BankTally.objects.filter(owner=self.user, account=self.bank).count(), 1)
        self.assertEqual(ChangeLog.objects.filter(owner=self.user, action="bank_tally_saved").count(), 1)
        self.assertEqual(bank_activity(self.user, self.bank, date(2025, 8, 1), date(2025, 9, 1)), {
            "credits": Decimal("10000.00"), "debits": Decimal("3700.00"),
        })
        self.assertEqual(bank_activity(self.user, second_bank, date(2025, 8, 1), date(2025, 9, 1)), {
           "credits": Decimal("200.00"), "debits": Decimal("0.00"),
        })

    def test_payment_check_supports_cash_and_wallet_modes(self):
        cash = Account.objects.get(owner=self.user, name="Cash")
        self.client.post(reverse("entry_add", args=["income"]), {
            "date": "2025-08-22", "amount": "500.00", "account": cash.pk, "source": "cash",
            "submission_token": str(uuid.uuid4()), "expected_revision": 0,
        })
        url = f"{reverse('bank_tally')}?month=2025-08&account={cash.pk}"
        response = self.client.post(url, {"account": cash.pk, "statement_credits": "500.00",
            "statement_debits": "0.00", "notes": "Cash count", "submission_token": str(uuid.uuid4()),
            "expected_revision": 0})
        self.assertEqual(response.status_code, 302)
        tally = BankTally.objects.get(owner=self.user, account=cash)
        self.assertEqual(tally.statement_credits, Decimal("500.00"))
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get(reverse("bank_tally"), {"month": "2025-08", "account": self.bank.pk})
        self.assertContains(response, "Statement credits")
        self.assertContains(response, "Bank 2")

    def test_monthly_report_sums_cash_and_operating_results(self):
        self.client.post(reverse("entry_add", args=["income"]), {
            "date": "2025-08-22", "sale_date": "2025-08-20", "recognized_amount": "10000.00",
            "amount": "10000.00", "account": self.bank.pk,
            "source": "razorpay", "submission_token": str(uuid.uuid4()), "expected_revision": 0,
        })
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(amount="3500.00"))
        add_stock(self.product, self.user, {"date": date(2025, 8, 1), "kind": "received", "quantity": 5,
                                            "submission_token": uuid.uuid4()})
        add_stock(self.product, self.user, {"date": date(2025, 8, 12), "kind": "sold", "quantity": 2,
                                            "submission_token": uuid.uuid4()})
        response = self.client.get(reverse("monthly_reports"), {"year": "2025"})
        self.assertEqual(response.context["month"], "2025-01")
        self.assertEqual(response.context["year_totals"]["income"], Decimal("10000.00"))
        self.assertEqual(response.context["year_totals"]["expense"], Decimal("3500.00"))
        self.assertEqual(response.context["year_totals"]["result"], Decimal("6500.00"))
        self.assertEqual(response.context["year_totals"]["cash_profit"], Decimal("6500.00"))
        self.assertEqual(response.context["year_totals"]["operating_profit"], Decimal("6500.00"))
        self.assertContains(response, "August 2025")
        self.assertContains(response, "FIFO cost of goods sold")

    def test_bank_tally_is_owner_scoped_and_closed_month_protected(self):
        foreign_bank = Account.objects.create(owner=self.other, name="Private bank", kind=Account.Kind.BANK)
        self.assertEqual(self.client.get(reverse("bank_tally"), {"account": foreign_bank.pk}).status_code, 404)
        MonthReview.objects.create(owner=self.user, month=date(2025, 8, 1), closed_at=timezone.now())
        tally_url = f"{reverse('bank_tally')}?month=2025-08&account={self.bank.pk}"
        response = self.client.post(tally_url, {
            "account": self.bank.pk, "statement_credits": "0.00", "statement_debits": "0.00",
            "notes": "", "submission_token": str(uuid.uuid4()), "expected_revision": 0,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is closed")
        self.assertFalse(BankTally.objects.filter(owner=self.user, account=self.bank).exists())

    def test_legacy_transactions_route_redirects_to_dashboard(self):
        response = self.client.get(reverse("transactions"), {"month": "2025-08", "kind": "expense"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/?month=2025-08&kind=expense")

    def test_inline_category_creation_preserves_unfinished_expense(self):
        payload = self.entry_data(amount="4250.00", reference="REF-KEEP", notes="Unfinished expense")
        payload.update({"inline_action": "category", "category-name": "Packaging material"})
        response = self.client.post(reverse("entry_add", args=["expense"]), payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Category.objects.filter(owner=self.user, name="Packaging material").exists())
        self.assertContains(response, 'value="4250.00"')
        self.assertContains(response, 'REF-KEEP')

    def test_save_and_add_another_uses_fresh_amount_and_reference(self):
        response = self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(amount="7500.00", reference="REFERENCE-123", notes="first entry", save_another="1"))
        self.assertEqual(response.status_code, 302)
        next_response = self.client.get(response.url)
        self.assertNotContains(next_response, 'value="7500.00"')
        self.assertNotContains(next_response, 'REFERENCE-123')

    def test_auth_and_csrf(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(reverse("entry_add", args=["expense"]), self.entry_data()).status_code, 403)

    def test_demo_refuses_nonempty_workspace(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", username=self.user.username)

    def test_defaults_idempotent(self):
        before = (Account.objects.count(), Category.objects.count())
        setup_defaults(self.user)
        self.assertEqual((Account.objects.count(), Category.objects.count()), before)

    def test_csv_escapes_formula_notes(self):
        self.client.post(reverse("entry_add", args=["expense"]), self.entry_data(notes="=HYPERLINK(\"bad\")"))
        response = self.client.get(reverse("export_csv"), {"month": "2025-08"})
        self.assertIn("'=HYPERLINK", response.content.decode())
