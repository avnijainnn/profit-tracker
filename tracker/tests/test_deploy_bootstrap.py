from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from io import StringIO
import os
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from tracker.models import Account, Entry, Product
from tracker.services import product_stats, report


class PrepareDeployConfigurationTests(TestCase):
    @patch("tracker.management.commands.prepare_deploy.connection")
    @patch("tracker.management.commands.prepare_deploy.call_command")
    def test_neon_pooler_uses_direct_host_for_migrations(self, child_commands, deploy_connection):
        deploy_connection.vendor = "postgresql"
        deploy_connection.settings_dict = {"HOST": "ep-example-pooler.region.aws.neon.tech"}
        call_command("prepare_deploy", stdout=StringIO())
        deploy_connection.close.assert_called_once()
        self.assertEqual(deploy_connection.settings_dict["HOST"], "ep-example.region.aws.neon.tech")
        self.assertEqual(child_commands.call_count, 2)
        self.assertEqual(deploy_connection.cursor.call_count, 2)


INITIAL_ENV = {
    "INITIAL_OWNER_USERNAME": "client-demo",
    "INITIAL_OWNER_EMAIL": "client@example.test",
    "INITIAL_OWNER_PASSWORD": "Private-test-only!8392026",
    "DEMO_SEED_DATA": "true",
}


@override_settings(DEMO_MODE=True)
class BootstrapTests(TestCase):
    def bootstrap(self):
        output = StringIO()
        call_command("bootstrap_workspace", stdout=output)
        self.assertNotIn(INITIAL_ENV["INITIAL_OWNER_PASSWORD"], output.getvalue())
        return output.getvalue()

    @patch.dict(os.environ, INITIAL_ENV)
    @patch("django.utils.timezone.localdate", return_value=date(2026, 1, 1))
    def test_first_start_creates_normal_user_and_reconciled_demo(self, _today):
        self.bootstrap()
        user = get_user_model().objects.get()
        self.assertTrue(user.check_password(INITIAL_ENV["INITIAL_OWNER_PASSWORD"]))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(Account.objects.filter(owner=user).count(), 7)
        totals = report(user, date(2025, 12, 1), date(2026, 1, 1))["totals"]
        self.assertEqual(totals["cash_profit"], Decimal("-5800.00"))
        self.assertEqual(totals["expense"], Decimal("5800.00"))
        self.assertEqual(totals["result"], Decimal("-5800.00"))
        cash = report(user, date(2026, 1, 1), date(2026, 2, 1))["totals"]
        self.assertEqual(cash["cash_profit"], Decimal("4000.00"))
        stats = product_stats(Product.objects.get(), date(2025, 12, 1), date(2026, 1, 1))
        self.assertEqual(stats["available"], 6)

    @patch.dict(os.environ, INITIAL_ENV)
    def test_restart_never_changes_password_or_duplicates_demo(self):
        self.bootstrap()
        user = get_user_model().objects.get()
        user.set_password("Changed-by-user!123")
        user.save()
        counts = (Entry.objects.count(), Product.objects.count())
        with patch.dict(os.environ, {"INITIAL_OWNER_PASSWORD": "", "INITIAL_OWNER_USERNAME": "new-name"}):
            self.bootstrap()
        user.refresh_from_db()
        self.assertTrue(user.check_password("Changed-by-user!123"))
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual((Entry.objects.count(), Product.objects.count()), counts)

    @patch.dict(os.environ, {**INITIAL_ENV, "INITIAL_OWNER_PASSWORD": ""})
    def test_empty_database_requires_initial_credentials(self):
        with self.assertRaises(CommandError):
            self.bootstrap()
        self.assertFalse(get_user_model().objects.exists())

    @patch.dict(os.environ, {**INITIAL_ENV, "INITIAL_OWNER_PASSWORD": "weak"})
    def test_weak_password_is_rejected_without_partial_workspace(self):
        with self.assertRaises(CommandError):
            self.bootstrap()
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Account.objects.exists())

    @patch.dict(os.environ, INITIAL_ENV)
    @override_settings(DEMO_MODE=False)
    def test_production_refuses_fictional_seed(self):
        with self.assertRaisesMessage(CommandError, "APP_ENV=demo"):
            self.bootstrap()
        self.assertFalse(get_user_model().objects.exists())

    @patch.dict(os.environ, {**INITIAL_ENV, "DEMO_SEED_DATA": "false"})
    @override_settings(DEMO_MODE=False)
    def test_empty_real_workspace_can_initialize_without_demo_data(self):
        self.bootstrap()
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertFalse(Entry.objects.exists())
        self.assertFalse(Product.objects.exists())

    @patch.dict(os.environ, INITIAL_ENV)
    @patch("tracker.management.commands.bootstrap_workspace.Command.seed_demo", side_effect=CommandError("failed seed"))
    def test_seed_failure_rolls_back_initial_user_and_accounts(self, _seed):
        with self.assertRaises(CommandError):
            self.bootstrap()
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Account.objects.exists())


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL advisory locks")
@override_settings(DEMO_MODE=True)
class BootstrapConcurrencyTests(TransactionTestCase):
    @patch.dict(os.environ, INITIAL_ENV)
    def test_two_starts_create_only_one_workspace(self):
        gate = Barrier(2)

        def start():
            try:
                gate.wait(timeout=10)
                call_command("bootstrap_workspace", stdout=StringIO())
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: start(), range(2)))
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Entry.objects.count(), 5)
