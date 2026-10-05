"""Run explicitly with config.stress_settings; never touches the client database."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from statistics import median
from threading import Barrier
from time import perf_counter
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tracker.forms import EntryForm
from tracker.models import Account, Category, Entry, InventoryLot, LotDepletion, Product, StockMovement
from tracker.services import add_stock, save_entry, setup_defaults
from tracker.summaries import monthly_totals, payment_totals, stock_totals, yearly_totals


class LargeWorkspaceStressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("stress-owner")
        setup_defaults(cls.owner)
        cls.accounts = list(Account.objects.filter(owner=cls.owner).exclude(kind="other"))
        cls.category = Category.objects.get(owner=cls.owner, name="Manufacturing")
        cls.products = Product.objects.bulk_create([
            Product(owner=cls.owner, sku=f"STRESS-{index:04}", name=f"Stress bag {index:04}") for index in range(200)])
        cls.expected = defaultdict(lambda: {"income": Decimal("0.00"), "expense": Decimal("0.00")})
        entries = []
        for index in range(10000):
            month = index % 12 + 1
            kind = "income" if index % 5 < 2 else "expense"
            amount = Decimal(index % 1499 + 1) / 100
            is_void = index % 23 == 0
            entries.append(Entry(owner=cls.owner, kind=kind, date=date(2025, month, index % 28 + 1),
                amount=amount, account=cls.accounts[index % len(cls.accounts)],
                source="cash" if kind == "income" else "", category=cls.category if kind == "expense" else None,
                product=cls.products[index % len(cls.products)] if kind == "expense" else None,
                voided_at=timezone.now() if is_void else None))
            if not is_void:
                cls.expected[month][kind] += amount
        Entry.objects.bulk_create(entries, batch_size=500)
        lots = InventoryLot.objects.bulk_create([
            InventoryLot(owner=cls.owner, product=product, received_date=date(2025, 1, 1), quantity_received=100)
            for product in cls.products])
        movements = []
        for product, lot in zip(cls.products, lots):
            movements.append(StockMovement(product=product, inventory_lot=lot, date=date(2025, 1, 1), kind="received", quantity=100))
            for day in range(2, 21):
                movements.append(StockMovement(product=product, date=date(2025, 1, day), kind="sold", quantity=1))
        StockMovement.objects.bulk_create(movements, batch_size=500)
        lot_ids = {lot.product_id: lot.pk for lot in lots}
        LotDepletion.objects.bulk_create([
            LotDepletion(movement=movement, lot_id=lot_ids[movement.product_id], quantity=1, unit_cost=0)
            for movement in movements if movement.kind == "sold"], batch_size=500)

    def setUp(self):
        self.client.force_login(self.owner)

    def test_ten_thousand_entries_match_independent_decimal_ledger(self):
        year = yearly_totals(self.owner, 2025)
        for month in range(1, 13):
            start = date(2025, month, 1)
            end = date(2026, 1, 1) if month == 12 else date(2025, month + 1, 1)
            amounts = self.expected[month]
            monthly = monthly_totals(self.owner, start, end)
            self.assertEqual(monthly["income"], amounts["income"])
            self.assertEqual(monthly["expense"], amounts["expense"])
            self.assertEqual(monthly["result"], amounts["income"] - amounts["expense"])
            self.assertEqual(year[month], monthly)
            self.assertEqual(payment_totals(self.owner, start, end)["totals"],
                             {"received": amounts["income"], "expenses": amounts["expense"]})
        balances = stock_totals(self.owner, date(2025, 1, 1), date(2025, 2, 1))
        self.assertEqual(len(balances), 200)
        for amounts in balances.values():
            self.assertEqual(amounts, {"available": 81, "stock_at_month_end": 81, "month_sold": 19})

    def test_repeated_pages_have_bounded_queries_and_correct_results(self):
        endpoints = [
            (reverse("dashboard") + "?month=2025-08", "Monthly tracker"),
            (reverse("monthly_reports") + "?year=2025", "Monthly reports"),
            (reverse("payment_summary") + "?month=2025-08", "Payment summary"),
            (reverse("products") + "?month=2025-08", "Products & stock"),
            (reverse("product_detail", args=[self.products[0].pk]) + "?month=2025-08", "Stock history"),
        ]
        elapsed = []
        query_max = 0
        for _ in range(10):
            for url, label in endpoints:
                started = perf_counter()
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(url)
                    self.assertContains(response, label)
                elapsed.append(perf_counter() - started)
                query_max = max(query_max, len(queries))
                self.assertLessEqual(len(queries), 15, (url, len(queries)))
        samples = sorted(elapsed)
        print(f"STRESS: 10000 money entries, 200 SKUs, 4000 stock movements; {len(samples)} page requests; "
              f"median={median(samples)*1000:.1f}ms p95={samples[int(len(samples)*0.95)-1]*1000:.1f}ms max_queries={query_max}")


class ConcurrentSubmissionStressTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor == "sqlite" and ("memory" in str(connection.settings_dict["NAME"])):
            self.skipTest("Use config.stress_settings for a disposable on-disk concurrency database.")
        self.owner = get_user_model().objects.create_user("race-owner")
        setup_defaults(self.owner)
        self.bank = Account.objects.get(owner=self.owner, name="Bank 1")
        self.category = Category.objects.get(owner=self.owner, name="Manufacturing")
        self.product = Product.objects.create(owner=self.owner, sku="RACE", name="Race bag")
        add_stock(self.product, self.owner, {"date": date(2025, 9, 1), "kind": "received", "quantity": 1})

    def concurrent(self, worker, count=8):
        gate = Barrier(count)
        def run(index):
            close_old_connections()
            try:
                gate.wait(timeout=30)
                return worker(index)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(run, range(count)))

    def test_eight_simultaneous_sales_cannot_oversell_one_unit(self):
        def sell(index):
            try:
                add_stock(self.product, self.owner, {"date": date(2025, 9, 2), "kind": "sold", "quantity": 1,
                          "submission_token": uuid.uuid4()})
                return "saved"
            except ValidationError:
                return "rejected"
        results = self.concurrent(sell)
        self.assertEqual(results.count("saved"), 1)
        self.assertEqual(results.count("rejected"), 7)
        self.assertEqual(StockMovement.objects.filter(kind="sold").count(), 1)

    def test_eight_retries_create_exactly_one_receipt(self):
        token = uuid.uuid4()
        results = self.concurrent(lambda index: add_stock(self.product, self.owner, {
            "date": date(2025, 9, 2), "kind": "received", "quantity": 3, "submission_token": token}).pk)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(StockMovement.objects.filter(kind="received").count(), 2)

    def expense_form(self, amount="0.01", token=None, instance=None):
        form = EntryForm({"date": "2025-09-02", "amount": amount, "category": self.category.pk,
                          "account": self.bank.pk, "expected_revision": instance.revision if instance else 0,
                          "submission_token": token or uuid.uuid4()},
                         owner=self.owner, kind="expense", instance=instance)
        if not form.is_valid():
            raise AssertionError(form.errors)
        return form

    def test_eight_money_retries_create_exactly_one_expense(self):
        token = uuid.uuid4()
        results = self.concurrent(lambda index: save_entry(self.expense_form(token=token), self.owner).pk)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(Entry.objects.count(), 1)
        self.assertEqual(monthly_totals(self.owner, date(2025, 9, 1), date(2025, 10, 1))["expense"], Decimal("0.01"))

    def test_eight_stale_money_edits_save_only_one_correction(self):
        original = save_entry(self.expense_form(amount="10.00"), self.owner)
        originals = [Entry.objects.get(pk=original.pk) for _ in range(8)]
        def edit(index):
            try:
                save_entry(self.expense_form(amount=str(20 + index), instance=originals[index]), self.owner)
                return "saved"
            except ValidationError:
                return "rejected"
        results = self.concurrent(edit)
        self.assertEqual(results.count("saved"), 1)
        self.assertEqual(results.count("rejected"), 7)
        original.refresh_from_db()
        self.assertEqual(original.revision, 2)

    def test_eight_duplicate_sku_forms_create_one_sku_without_server_errors(self):
        clients = [Client() for _ in range(8)]
        for client in clients:
            client.force_login(self.owner)
        results = self.concurrent(lambda index: clients[index].post(reverse("product_add"), {
            "sku": "SAME-SKU", "name": "Shared new SKU", "kind": "bag"}).status_code)
        self.assertEqual(results.count(302), 1)
        self.assertEqual(results.count(200), 7)
        self.assertEqual(Product.objects.filter(sku="SAME-SKU").count(), 1)

    def test_eight_duplicate_account_forms_create_one_account_without_server_errors(self):
        clients = [Client() for _ in range(8)]
        for client in clients:
            client.force_login(self.owner)
        results = self.concurrent(lambda index: clients[index].post(reverse("settings"), {
            "action": "account", "account-name": "Same account", "account-kind": "bank"}).status_code)
        self.assertEqual(results.count(302), 1)
        self.assertEqual(results.count(200), 7)
        self.assertEqual(Account.objects.filter(owner=self.owner, name="Same account").count(), 1)
