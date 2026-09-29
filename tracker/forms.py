from django import forms
from django.db.models import Q
import uuid
from django.utils import timezone
from .models import Account, Category, Entry, Product, StockMovement, Subcategory


class StyledForm(forms.ModelForm):
    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        if hasattr(self.instance, "owner_id"):
            self.instance.owner = owner
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            if isinstance(field, forms.ModelMultipleChoiceField):
                field.empty_label = None
            elif isinstance(field, forms.ModelChoiceField):
                field.empty_label = "Choose an option"
            elif isinstance(field, forms.ChoiceField):
                field.choices = [(value, "Choose an option" if value == "" else label)
                                 for value, label in field.choices]
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 3

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value > timezone.localdate():
            raise forms.ValidationError("Enter an actual transaction date, not a future date.")
        return value


class EntryForm(StyledForm):
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, initial=0)
    change_reason = forms.CharField(required=False, label="Reason for correction", widget=forms.Textarea)
    class Meta:
        model = Entry
        fields = ["date", "sale_date", "recognized_amount", "amount", "account", "source", "category", "subcategory", "product", "paid_by", "destination", "reference", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "sale_date": forms.DateInput(attrs={"type": "date"}), "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"})}

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.kind = kind
        self.fields["expected_revision"].initial = self.instance.revision if self.instance.pk else 0
        if self.instance.pk:
            self.fields["change_reason"].required = True
        else:
            self.fields.pop("change_reason")
        for name, model in (("account", Account), ("destination", Account), ("category", Category), ("subcategory", Subcategory), ("product", Product)):
            self.fields[name].queryset = model.objects.filter(owner=self.owner)
        for name, label in {"account": "Choose a payment account", "category": "Choose a category",
                            "product": "No product linked (optional)",
                            "destination": "External repayment / no destination"}.items():
            self.fields[name].empty_label = label
        if kind != Entry.Kind.EXPENSE:
            for name in ("category", "subcategory", "product", "paid_by"):
                self.fields.pop(name)
            self.fields["account"].queryset = self.fields["account"].queryset.exclude(kind=Account.Kind.OTHER)
        if kind != Entry.Kind.INCOME:
            self.fields.pop("source")
            self.fields.pop("sale_date")
            self.fields.pop("recognized_amount")
        if kind != Entry.Kind.TRANSFER:
            self.fields.pop("destination")
        if kind == Entry.Kind.INCOME:
            self.fields["source"].required = True
            self.fields["amount"].help_text = "Enter the net amount received. Do not deduct fees/refunds again."
            self.fields["date"].label = "Actual receipt date"
            self.fields["sale_date"].label = "Sale date (Operating Profit month)"
            self.fields["sale_date"].required = False
            self.fields["sale_date"].help_text = "Enter when the sales revenue was earned. Leave both fields blank for an advance or when not yet known."
            self.fields["recognized_amount"].label = "Sales revenue earned (optional)"
            self.fields["recognized_amount"].required = False
            self.fields["recognized_amount"].help_text = "Gross amount recognized for Operating Profit; can differ from this net cash receipt."
            self.fields["amount"].label = "Amount received"
            self.fields["account"].label = "Received in"
            # Preserve historical account choices when editing old receipts.
            self.fields["account"].queryset = self.fields["account"].queryset.filter(
                Q(kind__in=[Account.Kind.BANK, Account.Kind.CASH]) |
                Q(pk=self.instance.account_id if self.instance.pk else None))
            self.fields["source"].choices = [("", "Choose a source"), ("razorpay", "Razorpay"),
                                              ("cod", "COD"), ("upi", "Manual UPI"), ("cash", "Cash")]
        if kind == Entry.Kind.EXPENSE:
            self.fields["category"].required = True
            self.fields["subcategory"].required = False
            self.fields["subcategory"].queryset = Subcategory.objects.filter(owner=self.owner)
            self.fields["subcategory"].empty_label = "No subcategory (optional)"
            if not self.fields["subcategory"].queryset.exists():
                self.fields["subcategory"].widget = forms.HiddenInput()
            self.fields["date"].label = "Actual payment date"
            self.fields["account"].label = "Paid using"
            self.fields["product"].label = "Bag / product"
            self.fields["product"].help_text = "This payment will also appear in the product's spending history."
            self.fields["paid_by"].label = "Who paid?"
            self.fields["paid_by"].help_text = "Required for payments made by someone else. Cleared on save when you select your own account."
            self.order_fields(["date", "amount", "category", "account", "paid_by", "product", "reference", "notes"])
        elif kind == Entry.Kind.INCOME:
            self.order_fields(["date", "amount", "source", "account", "sale_date", "recognized_amount", "reference", "notes"])
        if kind == Entry.Kind.TRANSFER:
            self.fields["notes"].required = True
            self.fields["destination"].help_text = "Optional for an external reimbursement. This entry never affects the monthly result."

    def clean(self):
        data = super().clean()
        if self.instance.kind == Entry.Kind.INCOME and data.get("recognized_amount") and not data.get("sale_date"):
            data["sale_date"] = data.get("date")
        if data.get("sale_date") and data["sale_date"] > timezone.localdate():
            self.add_error("sale_date", "Enter an actual sale date, not a future date.")
        reference = data.get("reference", "").strip()
        data["reference"] = reference
        if self.instance.kind == Entry.Kind.EXPENSE:
            account = data.get("account")
            if account and account.kind != Account.Kind.OTHER:
                # The old value remains in the service's before snapshot on edits.
                data["paid_by"] = ""
        # The transaction service checks references after retry detection, under a lock.
        return data


class ProductForm(StyledForm):
    class Meta:
        model = Product
        fields = ["sku", "name", "kind", "selling_price", "active", "notes"]
    def clean_sku(self):
        sku = self.cleaned_data["sku"].strip().upper()
        if Product.objects.filter(owner=self.owner, sku=sku).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This SKU already exists in your workspace.")
        return sku


class StockForm(StyledForm):
    costs_confirmed = forms.BooleanField(required=False, label="I have entered the full landed cost (use zero for any cost that does not apply).")
    payment_date = forms.DateField(required=False, label="Actual payment date", widget=forms.DateInput(attrs={"type": "date"}))
    manufacturer = forms.CharField(required=False, max_length=160, label="Manufacturer / supplier")
    manufacturing_cost = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, label="Manufacturing cost", widget=forms.NumberInput(attrs={"min": "0", "step": "0.01"}))
    base_shipping_cost = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, label="Base shipping cost", widget=forms.NumberInput(attrs={"min": "0", "step": "0.01"}))
    extra_shipping_cost = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, label="Extra shipping cost", widget=forms.NumberInput(attrs={"min": "0", "step": "0.01"}))
    other_direct_cost = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, label="Other direct cost", widget=forms.NumberInput(attrs={"min": "0", "step": "0.01"}))
    payment_account = forms.ModelChoiceField(queryset=Account.objects.none(), required=False, label="Paid using")
    existing_cost_entries = forms.ModelMultipleChoiceField(queryset=Entry.objects.none(), required=False,
        label="Previously recorded product payments to include in this lot",
        help_text="Select existing manufacturing/shipping expenses so they are linked to this lot instead of entered twice.")
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    class Meta:
        model = StockMovement
        fields = ["date", "kind", "quantity", "batch_name", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "quantity": forms.NumberInput(attrs={"min": 1, "step": 1})}

    def __init__(self, *args, action=None, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        if action is None and self.is_bound:
            action = self.data.get("kind")
        if action in (StockMovement.Kind.RECEIVED, StockMovement.Kind.SOLD):
            self.fields["kind"].initial = action
            self.fields["kind"].disabled = True
            self.fields["kind"].widget = forms.HiddenInput()
        elif action == "more":
            self.fields["kind"].choices = [choice for choice in self.fields["kind"].choices
                                           if choice[0] not in (StockMovement.Kind.RECEIVED, StockMovement.Kind.SOLD)]
        self.fields.pop("sales_amount", None)
        if action != StockMovement.Kind.RECEIVED:
            for name in ("payment_date", "manufacturer", "manufacturing_cost", "base_shipping_cost", "extra_shipping_cost", "other_direct_cost", "payment_account", "costs_confirmed", "existing_cost_entries"):
                self.fields.pop(name)
        else:
            self.fields["payment_account"].queryset = Account.objects.filter(owner=self.owner).exclude(kind=Account.Kind.OTHER)
            if product:
                self.fields["existing_cost_entries"].queryset = Entry.objects.filter(owner=self.owner, kind=Entry.Kind.EXPENSE,
                    product=product, inventory_lot__isnull=True, capitalized_inventory_cost=False,
                    voided_at__isnull=True).select_related("account", "category").order_by("date", "pk")
            self.fields["existing_cost_entries"].label_from_instance = lambda row: (
                f"{row.date:%d %b %Y} · {row.category.name if row.category_id else 'Expense'} · "
                f"₹{row.amount} · {row.account.name}")
            if not self.fields["existing_cost_entries"].queryset.exists():
                self.fields["existing_cost_entries"].widget = forms.MultipleHiddenInput()
            for name, label in (("manufacturing_cost", "Additional manufacturing cost not already recorded"),
                                ("base_shipping_cost", "Additional base shipping not already recorded"),
                                ("extra_shipping_cost", "Additional extra shipping not already recorded"),
                                ("other_direct_cost", "Additional direct cost not already recorded")):
                self.fields[name].label = label
            self.fields["payment_date"].initial = timezone.localdate()
            for name in ("manufacturing_cost", "base_shipping_cost", "extra_shipping_cost", "other_direct_cost"):
                self.fields[name].initial = 0
        if action == StockMovement.Kind.SOLD:
            self.fields.pop("batch_name")
            self.fields["date"].label = "Sales date"
            self.fields["date"].help_text = "For a month-end total, use the last day of that month. For individual sales, use the actual sale date. Record earlier stock receipts first."
        elif action == StockMovement.Kind.RECEIVED:
            self.fields["date"].label = "Actual stock arrival date"
            self.fields["date"].help_text = "Stock date controls lot order. Payment date controls Cash Profit."

    def clean(self):
        data = super().clean()
        if data.get("kind") == StockMovement.Kind.RECEIVED:
            if not data.get("costs_confirmed"):
                self.add_error("costs_confirmed", "Confirm that all lot costs are entered before receiving stock.")
            for name in ("manufacturing_cost", "base_shipping_cost", "extra_shipping_cost", "other_direct_cost"):
                if data.get(name) is None:
                    data[name] = 0
            total = sum((data.get(n, 0) or 0 for n in ("manufacturing_cost", "base_shipping_cost", "extra_shipping_cost", "other_direct_cost")))
            if total and not data.get("payment_account"):
                self.add_error("payment_account", "Choose which account paid these stock costs.")
            data["payment_date"] = data.get("payment_date") or data.get("date")
            if data["payment_date"] and data["payment_date"] > timezone.localdate():
                self.add_error("payment_date", "Enter an actual payment date, not a future date.")
        return data


class AccountForm(StyledForm):
    class Meta:
        model = Account
        fields = ["name", "kind"]
    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Account.objects.filter(owner=self.owner, name__iexact=name).exists():
            raise forms.ValidationError("An account with this name already exists.")
        return name


class CategoryForm(StyledForm):
    class Meta:
        model = Category
        fields = ["name", "default_cost_behavior"]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_cost_behavior"].required = False
    def clean_default_cost_behavior(self):
        return self.cleaned_data.get("default_cost_behavior") or Category.CostBehavior.VARIABLE
    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Category.objects.filter(owner=self.owner, name__iexact=name).exists():
            raise forms.ValidationError("This category already exists.")
        return name


class BankTallyForm(forms.Form):
    statement_credits = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0,
                                           label="Statement credits", widget=forms.NumberInput(attrs={"min": "0", "step": "0.01", "class": "form-control"}))
    statement_debits = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0,
                                          label="Statement debits", widget=forms.NumberInput(attrs={"min": "0", "step": "0.01", "class": "form-control"}))
    notes = forms.CharField(required=False, label="Notes", widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}))
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, initial=0)


class ConfirmChangeForm(forms.Form):
    expected_revision = forms.IntegerField(required=False, widget=forms.HiddenInput)
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    reason = forms.CharField(min_length=5, max_length=1000, label="Reason", widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))
    confirm = forms.BooleanField(label="I have reviewed this change and want to proceed.")


class MonthReviewForm(ConfirmChangeForm):
    expected_state = forms.CharField(widget=forms.HiddenInput)
