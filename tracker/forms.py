from django import forms
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from PIL import Image, ImageOps
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
        if not self.instance.pk:
            self.fields.pop("change_reason")
        for name, model in (("account", Account), ("destination", Account), ("category", Category), ("subcategory", Subcategory), ("product", Product)):
            self.fields[name].queryset = model.objects.filter(owner=self.owner)
        self.fields["product"].queryset = self.fields["product"].queryset.filter(
            Q(active=True) | Q(pk=self.instance.product_id if self.instance.pk else None))
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
            self.fields.pop("sale_date")
            self.fields.pop("recognized_amount")
            self.fields["source"].required = True
            self.fields["amount"].help_text = "Enter the net amount received. Do not deduct fees/refunds again."
            self.fields["date"].label = "Actual receipt date"
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


class ProductPhotoInput(forms.ClearableFileInput):
    template_name = "tracker/photo_input.html"


class ProductForm(StyledForm):
    class Meta:
        model = Product
        fields = ["sku", "name", "photo", "kind", "notes"]
        widgets = {"photo": ProductPhotoInput(attrs={"accept": "image/jpeg,image/png,image/webp"})}

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not isinstance(photo, UploadedFile):
            return photo
        if photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Choose a photo smaller than 5 MB.")
        try:
            photo.seek(0)
            with Image.open(photo) as image:
                if image.format not in ("JPEG", "PNG", "WEBP"):
                    raise forms.ValidationError("Choose a JPG, PNG, or WebP photo.")
                if image.width * image.height > 16_000_000:
                    raise forms.ValidationError("Choose a photo with fewer than 16 million pixels.")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1200, 1200))
                output = BytesIO()
                image.save(output, format="JPEG", quality=88)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise forms.ValidationError("This photo could not be read. Choose another image.") from exc
        return SimpleUploadedFile("photo.jpg", output.getvalue(), content_type="image/jpeg")
    def clean_sku(self):
        sku = self.cleaned_data["sku"].strip().upper()
        if Product.objects.filter(owner=self.owner, sku=sku).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This SKU already exists in your workspace.")
        return sku


class StockForm(StyledForm):
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    class Meta:
        model = StockMovement
        fields = ["date", "kind", "quantity", "batch_name", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "quantity": forms.NumberInput(attrs={"min": 1, "step": 1})}

    def __init__(self, *args, action=None, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        action = action or (self.data.get("kind") if self.is_bound else StockMovement.Kind.RECEIVED)
        self.fields["kind"].choices = [("received", "Stock received"), ("sold", "Units sold")]
        if action in (StockMovement.Kind.RECEIVED, StockMovement.Kind.SOLD):
            self.fields["kind"].initial = action
            self.fields["kind"].disabled = True
            self.fields["kind"].widget = forms.HiddenInput()
        self.fields["date"].initial = timezone.localdate()
        if action == StockMovement.Kind.SOLD:
            self.fields.pop("batch_name")
            self.fields["date"].label = "Sales date"
        elif action == StockMovement.Kind.RECEIVED:
            self.fields["date"].label = "Actual stock arrival date"


class StockEditForm(StyledForm):
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    expected_state = forms.CharField(widget=forms.HiddenInput)

    class Meta:
        model = StockMovement
        fields = ["date", "quantity", "batch_name", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}),
                   "quantity": forms.NumberInput(attrs={"min": 1, "step": 1})}


class DeleteEntryForm(forms.Form):
    expected_revision = forms.IntegerField(widget=forms.HiddenInput)
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class DeleteProductForm(forms.Form):
    pass


class DeleteStockForm(forms.Form):
    expected_state = forms.CharField(widget=forms.HiddenInput)
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


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
        fields = ["name"]
    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if Category.objects.filter(owner=self.owner, name__iexact=name).exists():
            raise forms.ValidationError("This category already exists.")
        return name


class ConfirmChangeForm(forms.Form):
    expected_revision = forms.IntegerField(required=False, widget=forms.HiddenInput)
    submission_token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    reason = forms.CharField(min_length=5, max_length=1000, label="Reason", widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))
    confirm = forms.BooleanField(label="I have reviewed this change and want to proceed.")


class MonthReviewForm(ConfirmChangeForm):
    expected_state = forms.CharField(widget=forms.HiddenInput)
