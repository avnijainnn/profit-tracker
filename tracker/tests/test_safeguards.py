from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
import uuid
from unittest import skipUnless
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, close_old_connections, transaction, IntegrityError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from tracker.forms import EntryForm
from tracker.models import Account, Category, Entry, Product, StockMovement, StockReversal, MonthReview, Submission
from tracker.services import add_stock, change_month, product_stats, report, reverse_stock, save_entry, setup_defaults
from django.core import mail
from django.core.management import call_command


class SafeguardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("owner", email="owner@example.test", password="test-only-long-password")
        setup_defaults(self.user)
        self.bank = Account.objects.get(owner=self.user, name="Bank 1")
        self.category = Category.objects.get(owner=self.user, name="General")
        self.product = Product.objects.create(owner=self.user, sku="AQUA", name="Aqua")
        self.client.force_login(self.user)

    def payload(self, **changes):
        values = {"date": "2025-09-12", "amount": "100.00", "account": self.bank.pk,
                  "category": self.category.pk, "notes": "Test record", "submission_token": str(uuid.uuid4()), "expected_revision": 0}
        values.update(changes)
        return values

    def create_entry(self, values=None):
        form = EntryForm(values or self.payload(), owner=self.user, kind="expense")
        self.assertTrue(form.is_valid(), form.errors)
        return save_entry(form, self.user)

    def close_month(self, month="2025-09"):
        return change_month(self.user, month, close=True, reason="Checked all statements", expected_state="0", token=uuid.uuid4())

    def test_same_post_token_returns_single_entry(self):
        values = self.payload()
        first = self.create_entry(values)
        second = self.create_entry(values)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Entry.objects.count(), 1)

    def test_changed_payload_with_same_token_rejected(self):
        values = self.payload()
        self.create_entry(values)
        with self.assertRaises(ValidationError):
            self.create_entry({**values, "amount": "999"})
        self.assertEqual(Entry.objects.get().amount, Decimal("100"))

    def test_reference_has_database_constraint(self):
        self.create_entry(self.payload(reference="REF1"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Entry.objects.create(owner=self.user, kind="expense", date=date(2025, 9, 12), amount=100,
                                 account=self.bank, category=self.category, reference="REF1")

    def test_stale_editor_cannot_overwrite(self):
        entry = self.create_entry()
        stale = Entry.objects.get(pk=entry.pk)
        form = EntryForm(self.payload(amount="200", expected_revision=1, change_reason="Correct amount"), instance=entry, owner=self.user, kind="expense")
        self.assertTrue(form.is_valid(), form.errors)
        save_entry(form, self.user)
        stale_form = EntryForm(self.payload(amount="300", expected_revision=1, change_reason="Old tab edit"), instance=stale, owner=self.user, kind="expense")
        self.assertTrue(stale_form.is_valid(), stale_form.errors)
        with self.assertRaises(ValidationError):
            save_entry(stale_form, self.user)
        self.assertEqual(Entry.objects.get().amount, Decimal("200"))

    def test_closed_month_blocks_new_entry(self):
        self.close_month()
        with self.assertRaises(ValidationError):
            self.create_entry()

    def test_closed_month_blocks_moving_existing_entry_out(self):
        entry = self.create_entry()
        self.close_month()
        form = EntryForm(self.payload(date="2025-10-01", expected_revision=1, change_reason="Move to October"), instance=entry, owner=self.user, kind="expense")
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            save_entry(form, self.user)

    def test_reopen_requires_current_revision(self):
        review = self.close_month()
        with self.assertRaises(ValidationError):
            change_month(self.user, "2025-09", close=False, reason="Correction needed", expected_state="0", token=uuid.uuid4())
        change_month(self.user, "2025-09", close=False, reason="Correction needed", expected_state=str(review.revision), token=uuid.uuid4())
        self.create_entry()
        self.assertEqual(Entry.objects.count(), 1)

    def test_backdated_stock_blocked_by_later_closed_month(self):
        self.close_month()
        with self.assertRaises(ValidationError):
            add_stock(self.product, self.user, {"date": date(2025, 8, 1), "kind": "received", "quantity": 5})

    def test_stock_submission_idempotent(self):
        values = {"date": date(2025, 9, 1), "kind": "received", "quantity": 5, "submission_token": uuid.uuid4()}
        self.assertEqual(add_stock(self.product, self.user, values).pk, add_stock(self.product, self.user, values).pk)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_reversal_restores_stock_and_sales_stats(self):
        add_stock(self.product, self.user, {"date": date(2025, 9, 1), "kind": "received", "quantity": 10})
        sold = add_stock(self.product, self.user, {"date": date(2025, 9, 2), "kind": "sold", "quantity": 4})
        token = uuid.uuid4()
        first = reverse_stock(sold, self.user, reason="Mistaken quantity", token=token)
        self.assertEqual(first.pk, reverse_stock(sold, self.user, reason="Mistaken quantity", token=token).pk)
        self.assertEqual(StockMovement.objects.count(), 2)
        self.assertEqual(StockReversal.objects.count(), 1)
        stats = product_stats(self.product, date(2025, 9, 1), date(2025, 10, 1))
        self.assertEqual(stats["available"], 10)
        self.assertEqual(stats["month_sold"], 0)
        self.assertEqual(report(self.user, date(2025, 9, 1), date(2025, 10, 1))["sold_bags"], 0)

    def test_cannot_reverse_receipt_used_by_sales(self):
        receipt = add_stock(self.product, self.user, {"date": date(2025, 9, 1), "kind": "received", "quantity": 10})
        add_stock(self.product, self.user, {"date": date(2025, 9, 2), "kind": "sold", "quantity": 4})
        with self.assertRaises(ValidationError):
            reverse_stock(receipt, self.user, reason="Wrong receipt", token=uuid.uuid4())

    def test_unknown_route_is_404_not_security_middleware_500(self):
        self.assertEqual(self.client.get("/not-a-real-url/").status_code, 404)

    def test_health_response_contains_no_secrets(self):
        self.client.logout()
        response = self.client.get(reverse("health"))
        self.assertEqual(response.content, b"ok")

    def test_missing_submission_token_cannot_save(self):
        data = self.payload()
        data.pop("submission_token")
        response = self.client.post(reverse("entry_add", args=["expense"]), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Entry.objects.count(), 0)

    def test_reset_email_throttled_without_disclosing_account(self):
        self.user.email = "owner@example.test"
        self.user.save(update_fields=["email"])
        self.client.logout()
        for _ in range(4):
            response = self.client.post(reverse("password_reset"), {"email": self.user.email})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 3)
        unknown = self.client.post(reverse("password_reset"), {"email": "unknown@example.test"})
        self.assertEqual(unknown.url, reverse("password_reset_done"))

    @override_settings(PASSWORD_RESET_ENABLED=False)
    def test_demo_password_reset_endpoints_are_disabled(self):
        self.client.logout()
        routes = [
            reverse("password_reset"),
            reverse("password_reset_done"),
            reverse("password_reset_confirm", kwargs={"uidb64": "dXNlcg", "token": "invalid-token"}),
            reverse("password_reset_complete"),
        ]
        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 404)

    @override_settings(PASSWORD_RESET_ENABLED=False)
    def test_demo_login_does_not_offer_password_reset(self):
        self.client.logout()
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Forgot your password?")

    @override_settings(AXES_ENABLED=True)
    def test_login_failure_lockout(self):
        from django.contrib.auth import authenticate
        from django.test import RequestFactory
        factory = RequestFactory()
        for attempt in range(5):
            authenticate(request=factory.post("/account/login/", HTTP_USER_AGENT=f"browser-{attempt}",
                         HTTP_COOKIE=f"device={attempt}"), username="owner@example.test", password="incorrect")
        self.assertIsNone(authenticate(request=factory.post("/account/login/"), username="owner@example.test", password="test-only-long-password"))

    def test_auth_pages_render(self):
        self.client.logout()
        for route in ("login", "password_reset", "password_reset_done", "password_reset_complete"):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 200)

    @override_settings(DEBUG=True)
    def test_demo_seed_success_on_empty_user(self):
        demo = get_user_model().objects.create_user("demo-only")
        call_command("seed_demo", username=demo.username)
        self.assertEqual(Product.objects.filter(owner=demo).count(), 3)
        self.assertEqual(report(demo, date(2025, 9, 1), date(2025, 10, 1))["totals"]["income"], Decimal("103000"))


@skipUnless(connection.vendor == "postgresql", "Concurrency semantics require PostgreSQL")
class PostgreSQLConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("concurrent-owner")
        self.product = Product.objects.create(owner=self.user, sku="CONCURRENT", name="Concurrent stock")
        add_stock(self.product, self.user, {"date": date(2025, 9, 1), "kind": "received", "quantity": 1})

    def test_two_sales_cannot_oversell_last_unit(self):
        gate = Barrier(2)
        def attempt():
            close_old_connections()
            try:
                owner = get_user_model().objects.get(pk=self.user.pk)
                product = Product.objects.get(pk=self.product.pk)
                gate.wait(timeout=10)
                try:
                    add_stock(product, owner, {"date": date(2025, 9, 2), "kind": "sold", "quantity": 1})
                    return "saved"
                except ValidationError:
                    return "rejected"
            finally:
                # Worker threads must release even fresh persistent connections.
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(results, ["saved", "rejected"])

    def test_same_submission_concurrently_creates_one_stock_record(self):
        gate = Barrier(2)
        token = uuid.uuid4()
        def attempt():
            close_old_connections()
            try:
                owner = get_user_model().objects.get(pk=self.user.pk)
                product = Product.objects.get(pk=self.product.pk)
                gate.wait(timeout=10)
                return add_stock(product, owner, {"date": date(2025, 9, 2), "kind": "received", "quantity": 3, "submission_token": token}).pk
            finally:
                # Worker threads must release even fresh persistent connections.
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(StockMovement.objects.filter(kind="received").count(), 2)
