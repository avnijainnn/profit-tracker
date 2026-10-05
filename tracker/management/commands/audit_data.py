"""Read-only integrity and calculation checks; never changes client records."""
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.apps import apps

from tracker.domain import month_bounds, statement_summary, validate_stock_timeline
from tracker.models import Entry, LotDepletion, Product, StockReversal
from tracker.summaries import monthly_totals, payment_totals


class Command(BaseCommand):
    help = "Check database integrity, record validation, stock, and monthly totals without changing data."

    def handle(self, *args, **options):
        issues = []
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            issues.append("Database has unapplied migrations.")
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA integrity_check")
                if cursor.fetchall() != [("ok",)]:
                    issues.append("SQLite integrity check failed.")
                cursor.execute("PRAGMA foreign_key_check")
                if cursor.fetchall():
                    issues.append("Database has broken foreign keys.")
        records = 0
        for model in apps.get_app_config("tracker").get_models():
            for item in model.objects.all().iterator():
                records += 1
                try:
                    item.full_clean()
                except ValidationError as exc:
                    fields = ", ".join(sorted(getattr(exc, "message_dict", {"record": []})))
                    issues.append(f"{model.__name__} #{item.pk}: invalid {fields}.")
        groups = defaultdict(list)
        for entry in Entry.objects.filter(voided_at__isnull=True).select_related("account"):
            groups[(entry.owner_id, entry.date.strftime("%Y-%m"))].append(entry)
        months = 0
        from django.contrib.auth import get_user_model
        owners = {user.pk: user for user in get_user_model().objects.all()}
        for (owner_id, month), entries in groups.items():
            months += 1
            start, end = month_bounds(month)
            expected = statement_summary(entries)
            actual = monthly_totals(owners[owner_id], start, end)
            payments = payment_totals(owners[owner_id], start, end)["totals"]
            if any(actual[key] != expected[key] for key in ("income", "expense", "result", "withdrawal", "transfer")):
                issues.append(f"Workspace #{owner_id}, {month}: monthly totals differ from ledger.")
            if payments["received"] != expected["income"] or payments["expenses"] != expected["expense"]:
                issues.append(f"Workspace #{owner_id}, {month}: payment summary differs from ledger.")
        for product in Product.objects.all():
            movements = product.movements.filter(reversal__isnull=True).order_by("date", "pk")
            try:
                validate_stock_timeline(movements)
            except ValueError:
                issues.append(f"Product #{product.pk}: negative stock timeline.")
            if product.photo and not product.photo.storage.exists(product.photo.name):
                issues.append(f"Product #{product.pk}: photo file is missing.")
        for allocation in LotDepletion.objects.select_related("movement__product", "lot"):
            if allocation.movement.product_id != allocation.lot.product_id:
                issues.append(f"LotDepletion #{allocation.pk}: product mismatch.")
        for reversal in StockReversal.objects.select_related("movement__product"):
            if reversal.owner_id != reversal.movement.product.owner_id:
                issues.append(f"StockReversal #{reversal.pk}: workspace mismatch.")
        if issues:
            for issue in issues:
                self.stderr.write(issue)
            raise CommandError(f"Audit found {len(issues)} issue(s); no data changed.")
        self.stdout.write(self.style.SUCCESS(
            f"Audit passed: {records} validated records, {months} payment-month groups; no data changed."))
