"""Initial schema. Kept explicit so a fresh checkout only needs migrate."""
from decimal import Decimal
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="Account",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("kind", models.CharField(choices=[("bank", "Bank / UPI"), ("cash", "Cash"), ("card", "Credit card"), ("wallet", "Wallet / gift card"), ("other", "Paid by someone else")], default="bank", max_length=12)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name"], "constraints": [models.UniqueConstraint(fields=("owner", "name"), name="unique_owner_account")]},
        ),
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name"], "verbose_name_plural": "categories", "constraints": [models.UniqueConstraint(fields=("owner", "name"), name="unique_owner_category")]},
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sku", models.CharField(max_length=60, verbose_name="SKU / design code")),
                ("name", models.CharField(max_length=140)),
                ("kind", models.CharField(choices=[("bag", "Bag"), ("thrift", "Thrift item")], default="bag", max_length=10)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name"], "constraints": [models.UniqueConstraint(fields=("owner", "sku"), name="unique_owner_sku")]},
        ),
        migrations.CreateModel(
            name="Entry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("income", "Money received"), ("expense", "Expense"), ("withdrawal", "Owner withdrawal"), ("transfer", "Transfer / repayment (excluded)")], max_length=12)),
                ("date", models.DateField(db_index=True, verbose_name="Actual payment / receipt date")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
                ("source", models.CharField(blank=True, choices=[("razorpay", "Razorpay settlement"), ("cod", "COD settlement"), ("upi", "Manual UPI sale"), ("cash", "Cash sale")], max_length=12)),
                ("paid_by", models.CharField(blank=True, max_length=100, verbose_name="Payer name")),
                ("reference", models.CharField(blank=True, max_length=160, verbose_name="Statement reference (optional)")),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="entries", to="tracker.account")),
                ("destination", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transfers_in", to="tracker.account")),
                ("category", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="tracker.category")),
                ("product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="entries", to="tracker.product")),
            ],
            options={"ordering": ["-date", "-pk"], "indexes": [models.Index(fields=["owner", "date"], name="entry_owner_date")], "constraints": [models.CheckConstraint(condition=models.Q(amount__gt=0), name="entry_positive_amount")]},
        ),
        migrations.CreateModel(
            name="StockMovement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(verbose_name="Actual stock / sales date")),
                ("kind", models.CharField(choices=[("received", "Stock received / new batch"), ("sold", "Units sold"), ("returned", "Saleable return (add back)"), ("damaged", "Remove damaged stock"), ("adjust_in", "Opening stock / adjustment in"), ("adjust_out", "Adjustment out")], max_length=12)),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ("batch_name", models.CharField(blank=True, max_length=120, verbose_name="Batch / delivery label (optional)")),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="movements", to="tracker.product")),
            ],
            options={"ordering": ["date", "pk"], "constraints": [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="stock_positive_quantity")]},
        ),
        migrations.CreateModel(
            name="ChangeLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=40)),
                ("object_label", models.CharField(max_length=200)),
                ("details", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
