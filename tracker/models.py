from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from decimal import Decimal
import uuid


def product_photo_path(instance, filename):
    return f"products/{instance.owner_id}/{uuid.uuid4().hex}.jpg"


class OwnedModel(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    class Meta:
        abstract = True


class Account(OwnedModel):
    class Kind(models.TextChoices):
        BANK = "bank", "Bank / UPI"
        CASH = "cash", "Cash"
        CARD = "card", "Credit card"
        WALLET = "wallet", "Wallet / gift card"
        OTHER = "other", "Paid by someone else"
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.BANK)
    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="unique_owner_account")]
    def __str__(self):
        return self.name


class Category(OwnedModel):
    class CostBehavior(models.TextChoices):
        FIXED = "fixed", "Fixed"
        VARIABLE = "variable", "Variable"
        SPECIAL = "special", "Special"
        TAX = "tax", "Tax"
        INVENTORY = "inventory", "Inventory cost"
    name = models.CharField(max_length=100)
    default_cost_behavior = models.CharField(max_length=12, choices=CostBehavior.choices, default=CostBehavior.VARIABLE)
    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="unique_owner_category")]
    def __str__(self):
        return self.name


class Subcategory(OwnedModel):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="subcategories")
    name = models.CharField(max_length=100)
    default_cost_behavior = models.CharField(max_length=12, choices=Category.CostBehavior.choices,
                                             default=Category.CostBehavior.VARIABLE)
    class Meta:
        ordering = ["category__name", "name"]
        constraints = [models.UniqueConstraint(fields=["owner", "category", "name"], name="unique_owner_category_subcategory")]

    def clean(self):
        super().clean()
        if self.category_id and self.category.owner_id != self.owner_id:
            raise ValidationError({"category": "Choose a category from your workspace."})


class Product(OwnedModel):
    sku = models.CharField("SKU / design code", max_length=60)
    name = models.CharField(max_length=140)
    photo = models.ImageField(upload_to=product_photo_path, blank=True)
    class Kind(models.TextChoices):
        BAG = "bag", "Bag"
        THRIFT = "thrift", "Thrift item"
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BAG)
    notes = models.TextField(blank=True)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "sku"], name="unique_owner_sku")]
    def __str__(self):
        return f"{self.name} · {self.sku}"


class StoredUpload(models.Model):
    """Small private uploads stored with the records on hosts without durable disks."""

    path = models.CharField(max_length=255, primary_key=True)
    data = models.BinaryField()


class Entry(OwnedModel):
    class Kind(models.TextChoices):
        INCOME = "income", "Money received"
        EXPENSE = "expense", "Expense"
        WITHDRAWAL = "withdrawal", "Owner withdrawal"
        TRANSFER = "transfer", "Transfer / repayment (excluded)"
    class Source(models.TextChoices):
        RAZORPAY = "razorpay", "Razorpay settlement"
        COD = "cod", "COD settlement"
        UPI = "upi", "Manual UPI sale"
        CASH = "cash", "Cash sale"
    kind = models.CharField(max_length=12, choices=Kind.choices)
    date = models.DateField("Actual payment / receipt date", db_index=True)
    # Income has two timelines: `date` is cash received; sale_date is earned revenue.
    sale_date = models.DateField(null=True, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    recognized_amount = models.DecimalField("Recognized sales amount", max_digits=12, decimal_places=2,
        null=True, blank=True, validators=[MinValueValidator(Decimal("0.01"))])
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="entries")
    destination = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT, related_name="transfers_in")
    source = models.CharField(max_length=12, choices=Source.choices, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT)
    subcategory = models.ForeignKey(Subcategory, null=True, blank=True, on_delete=models.PROTECT, related_name="entries")
    cost_behavior = models.CharField(max_length=12, choices=Category.CostBehavior.choices,
                                     default=Category.CostBehavior.VARIABLE)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT, related_name="entries")
    inventory_lot = models.ForeignKey("InventoryLot", null=True, blank=True, on_delete=models.PROTECT, related_name="cost_entries")
    capitalized_inventory_cost = models.BooleanField(default=False)
    paid_by = models.CharField("Payer name", max_length=100, blank=True)
    reference = models.CharField("Statement reference (optional)", max_length=160, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    class Meta:
        ordering = ["-date", "-pk"]
        indexes = [models.Index(fields=["owner", "date"], name="entry_owner_date")]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="entry_positive_amount"),
            models.UniqueConstraint(fields=["owner", "account", "reference"],
                condition=models.Q(voided_at__isnull=True) & ~models.Q(reference=""), name="unique_active_statement_reference"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        for name in ("account", "destination", "category", "subcategory", "product"):
            related = getattr(self, name, None) if getattr(self, f"{name}_id", None) else None
            if related and related.owner_id != self.owner_id:
                errors[name] = "Choose an item from your workspace."
        if self.inventory_lot_id and (self.inventory_lot.owner_id != self.owner_id or
                (self.product_id and self.inventory_lot.product_id != self.product_id)):
            errors["inventory_lot"] = "Choose a stock lot for this product in your workspace."
        if self.kind == self.Kind.INCOME and not self.source:
            errors["source"] = "Choose the payment source."
        if self.kind == self.Kind.INCOME and self.recognized_amount and not self.sale_date:
            errors["sale_date"] = "Choose the date this sales revenue was earned."
        if self.kind != self.Kind.INCOME and (self.sale_date or self.recognized_amount):
            errors["sale_date"] = "Sale timing and sales amount are only for income."
        if self.kind != self.Kind.INCOME and self.source:
            errors["source"] = "Payment source is only for incoming sales receipts."
        if self.kind == self.Kind.EXPENSE and not self.category_id:
            errors["category"] = "Choose an expense category."
        if self.subcategory_id and (not self.category_id or self.subcategory.category_id != self.category_id):
            errors["subcategory"] = "Choose a subcategory within the selected category."
        if self.kind != self.Kind.EXPENSE and self.category_id:
            errors["category"] = "Category is only for expenses."
        if self.product_id and self.kind != self.Kind.EXPENSE:
            errors["product"] = "SKU cost links are only for expenses, not sales revenue."
        if self.destination_id and self.kind != self.Kind.TRANSFER:
            errors["destination"] = "Destination is only for transfers."
        if self.destination_id and self.destination_id == self.account_id:
            errors["destination"] = "Choose a different destination account."
        if self.account_id and self.account.kind == Account.Kind.OTHER:
            if self.kind != self.Kind.EXPENSE:
                errors["account"] = "Use this account type only for expenses paid by someone else."
            if not self.paid_by.strip():
                errors["paid_by"] = "Who paid this expense?"
        if self.kind == self.Kind.TRANSFER and not self.notes.strip():
            errors["notes"] = "Explain the transfer or repayment so it is easy to review."
        if self.capitalized_inventory_cost and (self.kind != self.Kind.EXPENSE or not self.inventory_lot_id):
            errors["inventory_lot"] = "An inventory cost must link to a stock lot expense."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.date} · {self.get_kind_display()} · ₹{self.amount}"


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        RECEIVED = "received", "Stock received / new batch"
        SOLD = "sold", "Units sold"
        RETURNED = "returned", "Saleable return (add back)"
        DAMAGED = "damaged", "Remove damaged stock"
        ADJUST_IN = "adjust_in", "Opening stock / adjustment in"
        ADJUST_OUT = "adjust_out", "Adjustment out"
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    date = models.DateField("Actual stock / sales date")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    sales_amount = models.DecimalField("SKU sales total (optional)", max_digits=12, decimal_places=2,
                                       null=True, blank=True, validators=[MinValueValidator(Decimal("0.01"))])
    batch_name = models.CharField("Batch / delivery label (optional)", max_length=120, blank=True)
    inventory_lot = models.ForeignKey("InventoryLot", null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["date", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="stock_positive_quantity"),
            models.CheckConstraint(condition=models.Q(sales_amount__isnull=True) | models.Q(kind="sold"),
                                   name="stock_sales_amount_only_for_sales"),
            models.CheckConstraint(condition=models.Q(sales_amount__isnull=True) | models.Q(sales_amount__gte=Decimal("0.01")),
                                   name="stock_sales_amount_positive"),
        ]

    def clean(self):
        super().clean()
        if self.sales_amount is not None and self.kind != self.Kind.SOLD:
            raise ValidationError({"sales_amount": "A SKU sales total can only be recorded with units sold."})

    def __str__(self):
        return f"{self.product.sku} · {self.get_kind_display()} · {self.quantity}"


class InventoryLot(OwnedModel):
    """A dated receipt whose landed cost is assigned to units by FIFO."""
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="lots")
    received_date = models.DateField(db_index=True)
    quantity_received = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    manufacturer = models.CharField(max_length=160, blank=True)
    manufacturing_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    base_shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    extra_shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    other_direct_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    batch_name = models.CharField(max_length=120, blank=True)
    costs_confirmed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity_received__gt=0), name="inventory_lot_qty_positive"),
            models.CheckConstraint(condition=models.Q(manufacturing_cost__gte=0), name="inventory_lot_mfg_nonnegative"),
            models.CheckConstraint(condition=models.Q(base_shipping_cost__gte=0), name="inventory_lot_base_ship_nonnegative"),
            models.CheckConstraint(condition=models.Q(extra_shipping_cost__gte=0), name="inventory_lot_extra_ship_nonnegative"),
            models.CheckConstraint(condition=models.Q(other_direct_cost__gte=0), name="inventory_lot_other_nonnegative"),
        ]

    def clean(self):
        super().clean()
        if self.product_id and self.product.owner_id != self.owner_id:
            raise ValidationError({"product": "Choose a product from this workspace."})

    @property
    def landed_cost(self):
        return sum((self.manufacturing_cost, self.base_shipping_cost,
                    self.extra_shipping_cost, self.other_direct_cost), Decimal("0.00"))

    @property
    def landed_cost_per_unit(self):
        if not self.quantity_received:
            return Decimal("0.00")
        return self.landed_cost / self.quantity_received


class LotDepletion(models.Model):
    """Immutable FIFO allocation from a stock sale to one received lot."""
    movement = models.ForeignKey(StockMovement, on_delete=models.PROTECT, related_name="lot_depletions")
    lot = models.ForeignKey(InventoryLot, on_delete=models.PROTECT, related_name="depletions")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_cost = models.DecimalField(max_digits=16, decimal_places=6, validators=[MinValueValidator(Decimal("0.000000"))])

    class Meta:
        ordering = ["lot__received_date", "lot_id"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="lot_depletion_positive_qty"),
                       models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="lot_depletion_nonnegative_cost")]


class BankTally(OwnedModel):
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="monthly_tallies")
    month = models.DateField()
    statement_credits = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"),
                                            validators=[MinValueValidator(Decimal("0.00"))])
    statement_debits = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"),
                                           validators=[MinValueValidator(Decimal("0.00"))])
    notes = models.TextField(blank=True)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-month", "account__name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "account", "month"], name="unique_owner_account_month_tally"),
            models.CheckConstraint(condition=models.Q(statement_credits__gte=0), name="bank_tally_credits_nonnegative"),
            models.CheckConstraint(condition=models.Q(statement_debits__gte=0), name="bank_tally_debits_nonnegative"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.account_id:
            if self.account.owner_id != self.owner_id:
                errors["account"] = "Choose a payment account from your workspace."
            elif self.account.kind == Account.Kind.OTHER:
                errors["account"] = "Third-party payer labels cannot be reconciled as payment accounts."
        if self.month and self.month.day != 1:
            errors["month"] = "Choose the first day of the statement month."
        if errors:
            raise ValidationError(errors)


class ChangeLog(OwnedModel):
    action = models.CharField(max_length=40)
    object_label = models.CharField(max_length=200)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at", "-pk"]


class Submission(OwnedModel):
    """A receipt for a committed mutation; retries return the existing outcome."""
    token = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    object_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "token"], name="unique_owner_submission")]


class MonthReview(OwnedModel):
    month = models.DateField()
    closed_at = models.DateTimeField(null=True, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    revision = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ["-month"]
        constraints = [models.UniqueConstraint(fields=["owner", "month"], name="unique_owner_review")]


class StockReversal(OwnedModel):
    """Cancels a mistaken movement in its ORIGINAL month; never erases it."""
    movement = models.OneToOneField(StockMovement, on_delete=models.PROTECT, related_name="reversal")
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at", "-pk"]


class RecoveryThrottle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    window_started = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
