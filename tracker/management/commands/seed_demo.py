"""Explicit opt-in fictional data; never generates a user or a password."""
from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings
from tracker.models import Account, Category, ChangeLog, Entry, Product
from tracker.services import add_stock, setup_defaults


class Command(BaseCommand):
    help = "Add fictional August/September 2025 data to an EMPTY user workspace."
    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo seeding is disabled when DEBUG is false. Use a separate local demo database.")
        try:
            owner = get_user_model().objects.get(username=options["username"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError("Create a user first: python manage.py createsuperuser") from exc
        if Entry.objects.filter(owner=owner).exists() or Product.objects.filter(owner=owner).exists():
            raise CommandError("Demo data requires an empty workspace. No existing data was changed.")
        setup_defaults(owner)
        bank = Account.objects.get(owner=owner, name="Bank 1")
        cash = Account.objects.get(owner=owner, name="Cash")
        card = Account.objects.get(owner=owner, name="Credit card")
        other = Account.objects.get(owner=owner, name="Paid by someone else")
        aqua = Product.objects.create(owner=owner, sku="DEMO-AQUA", name="Aqua Babe (demo)", notes="Fictional example: August advance, September delivery.")
        daisy = Product.objects.create(owner=owner, sku="DEMO-DAISY", name="Daisy Day (demo)")
        thrift = Product.objects.create(owner=owner, sku="DEMO-THRIFT", name="Vintage finds (demo)", kind="thrift")
        def entry(kind, amount, day, account=bank, month=9, category=None, **extra):
            row = Entry(owner=owner, kind=kind, amount=Decimal(amount), date=date(2025, month, day),
                        sale_date=date(2025, month, day) if kind == "income" else None, account=account,
                        category=Category.objects.get(owner=owner, name=category) if category else None, **extra)
            row.full_clean()
            row.save()
            return row
        aqua_advance = entry("expense", "35000", 22, month=8, category="Manufacturing", product=aqua, notes="DEMO · Advance. Stock arrives next month.")
        daisy_cost = entry("expense", "18000", 2, category="Manufacturing", product=daisy, notes="DEMO · Daisy production")
        aqua_shipping = entry("expense", "1600", 4, category="Shipping & transit", product=aqua, notes="DEMO · Inbound shipping")
        entry("expense", "3500", 7, account=card, category="Packaging material", notes="DEMO · Credit-card purchase, not bill settlement")
        entry("expense", "700", 8, account=other, paid_by="Demo helper", category="Shipping & transit", notes="DEMO · Paid on Tanvi's behalf")
        entry("expense", "4500", 11, category="Shipping & transit")
        entry("expense", "2500", 15, category="Refund", notes="DEMO · Manual UPI refund outside net settlement")
        entry("expense", "1999", 18, category="Tech & subscriptions")
        entry("expense", "900", 20, account=cash, category="General")
        entry("income", "22450", 5, source="razorpay", reference="DEMO-RZ-001")
        entry("income", "31800", 12, source="razorpay", reference="DEMO-RZ-002")
        entry("income", "27250", 19, source="razorpay", reference="DEMO-RZ-003")
        entry("income", "12000", 22, source="upi")
        entry("income", "5000", 25, account=cash, source="cash")
        entry("income", "4500", 26, source="cod")
        entry("withdrawal", "10000", 28, notes="DEMO · Owner withdrawal")
        entry("transfer", "3500", 29, destination=card, notes="DEMO · Card-bill payment; original purchase is already an expense")
        entry("transfer", "700", 29, notes="DEMO · Repay Demo helper; original expense counted only once")
        for product, qty, sold in ((aqua, 50, 12), (daisy, 30, 8), (thrift, 10, 3)):
            receipt = {"date": date(2025, 9, 3), "kind": "received", "quantity": qty,
                       "batch_name": "Demo September delivery", "notes": "Fictional demo data"}
            if product == aqua:
                receipt.update(existing_cost_entries=[aqua_advance, aqua_shipping], costs_confirmed=True)
            elif product == daisy:
                receipt.update(existing_cost_entries=[daisy_cost], costs_confirmed=True)
            add_stock(product, owner, receipt)
            add_stock(product, owner, {"date": date(2025, 9, 30), "kind": "sold", "quantity": sold, "batch_name": "", "notes": "DEMO · Month-end quantity total"})
        ChangeLog.objects.create(owner=owner, action="demo_seeded", object_label="Fictional demo workspace", details={"month": "2025-09"})
        self.stdout.write(self.style.SUCCESS("Demo ready. Open http://127.0.0.1:8000/?month=2025-09 . No real data was used."))
