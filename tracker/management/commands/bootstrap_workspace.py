"""Create only the first workspace; never reset users or seed an existing DB."""
from datetime import timedelta
from decimal import Decimal
import os
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from tracker.forms import EntryForm
from tracker.models import Account, Category, ChangeLog, Product
from tracker.services import add_stock, save_entry, setup_defaults


class Command(BaseCommand):
    help = "Create the first normal workspace account from INITIAL_OWNER_* environment variables."

    @transaction.atomic
    def handle(self, *args, **options):
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [7319041202])
        User = get_user_model()
        if User.objects.exists():
            self.stdout.write("Workspace already initialized; users, passwords and data left unchanged.")
            return
        username = os.environ.get("INITIAL_OWNER_USERNAME", "").strip()
        email = os.environ.get("INITIAL_OWNER_EMAIL", "").strip()
        password = os.environ.get("INITIAL_OWNER_PASSWORD", "")
        if not all((username, email, password)):
            raise CommandError("Empty database: set INITIAL_OWNER_USERNAME, INITIAL_OWNER_EMAIL and INITIAL_OWNER_PASSWORD.")
        seed_demo = os.environ.get("DEMO_SEED_DATA", "false").lower() == "true"
        if seed_demo and not settings.DEMO_MODE:
            raise CommandError("Fictional startup data requires APP_ENV=demo. Set DEMO_SEED_DATA=false for a real workspace.")
        user = User(username=username, email=email, is_staff=False, is_superuser=False)
        try:
            validate_password(password, user)
            user.set_password(password)
            user.full_clean()
        except ValidationError as exc:
            raise CommandError("Initial account validation failed: " + "; ".join(exc.messages)) from exc
        user.save()
        setup_defaults(user)
        if seed_demo:
            self.seed_demo(user)
        ChangeLog.objects.create(owner=user, action="workspace_initialized", object_label="Initial workspace",
                                 details={"fictional_data": seed_demo})
        self.stdout.write(self.style.SUCCESS("Initial workspace created. Sign in and enroll an authenticator."))

    def seed_demo(self, user):
        # Last completed month matches the app's initial review month, including
        # January/year boundaries. Every sample date is in the past or today.
        cash_month = timezone.localdate().replace(day=1)
        sale_month = (cash_month - timedelta(days=1)).replace(day=1)
        bank = Account.objects.get(owner=user, name="Bank 1")
        wallet = Account.objects.get(owner=user, name="CRED wallet")
        category = Category.objects.get(owner=user, name="General")
        product = Product.objects.create(owner=user, sku="DEMO-TOTE", name="Everyday tote (demo)",
                                         selling_price=Decimal("1000.00"), notes="Fictional client walkthrough")
        add_stock(product, user, {"date": sale_month.replace(day=5), "payment_date": sale_month.replace(day=5),
            "kind": "received", "quantity": 10, "batch_name": "Demo opening batch", "manufacturer": "Demo supplier",
            "manufacturing_cost": Decimal("5000.00"), "base_shipping_cost": Decimal("500.00"),
            "payment_account": bank, "costs_confirmed": True, "submission_token": uuid.uuid4()})
        add_stock(product, user, {"date": sale_month.replace(day=15), "kind": "sold", "quantity": 4,
                                 "notes": "DEMO: four tote bags sold", "submission_token": uuid.uuid4()})
        entries = [
            ("income", {"date": cash_month, "sale_date": sale_month.replace(day=15),
                        "recognized_amount": "4000.00", "amount": "4000.00", "source": "upi"}),
            ("expense", {"date": sale_month.replace(day=20), "amount": "300.00", "category": category.pk}),
            ("transfer", {"date": sale_month.replace(day=21), "amount": "200.00", "destination": wallet.pk}),
        ]
        for kind, data in entries:
            form = EntryForm({"account": bank.pk, "expected_revision": 0, "submission_token": uuid.uuid4(),
                              "notes": "Fictional demo transaction", **data}, owner=user, kind=kind)
            if not form.is_valid():
                raise CommandError("Fictional demo transaction failed validation; initialization rolled back.")
            save_entry(form, user)
        self.stdout.write(f"Fictional walkthrough loaded for {sale_month:%Y-%m}; cash receipt is in {cash_month:%Y-%m}.")
