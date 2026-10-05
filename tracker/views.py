import csv
from decimal import Decimal
from datetime import date
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction, connection, DatabaseError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_safe
from .domain import safe_csv_cell
from .forms import AccountForm, CategoryForm, EntryForm, ProductForm, StockForm, StockEditForm, DeleteEntryForm, DeleteStockForm, DeleteProductForm, ConfirmChangeForm, MonthReviewForm
from .models import Account, Category, ChangeLog, Entry, Product, StockMovement, MonthReview
from .services import add_stock, chosen_month, entry_snapshot, monthly_entries, save_entry, void_entry, reverse_stock, change_month, edit_stock, stock_state
from .summaries import EMPTY_STOCK, monthly_totals, money_totals, payment_totals, stock_totals, yearly_totals
from .guards import lock_workspace


def show_validation(form, exc):
    for message in exc.messages:
        form.add_error(None, message)


def month_url(name, month, **kwargs):
    return reverse(name, kwargs=kwargs) + f"?month={month}"


@login_required
def dashboard(request):
    context = chosen_month(request)
    context["totals"] = monthly_totals(request.user, context["month_start"], context["month_end"])
    context["has_accounts"] = Account.objects.filter(owner=request.user).exists()
    context["review"] = MonthReview.objects.filter(owner=request.user, month=context["month_start"]).first()
    entries = monthly_entries(request.user, context["month_start"], context["month_end"])
    kind = request.GET.get("kind", "all")
    if kind not in Entry.Kind.values and kind != "all":
        kind = "all"
    query = request.GET.get("q", "").strip()
    if kind in Entry.Kind.values:
        entries = entries.filter(kind=kind)
    if query:
        entries = entries.filter(Q(notes__icontains=query) | Q(reference__icontains=query) |
                                 Q(category__name__icontains=query) | Q(product__name__icontains=query) |
                                 Q(product__sku__icontains=query) | Q(account__name__icontains=query) |
                                 Q(paid_by__icontains=query) | Q(source__icontains=query))
    context.update({"page": Paginator(entries, 50).get_page(request.GET.get("page")), "kind": kind, "q": query})
    return render(request, "tracker/dashboard.html", context)

@login_required
def monthly_reports(request):
    current_year = timezone.localdate().year
    try:
        year = int(request.GET.get("year", current_year))
        if not 1900 <= year <= 9998:
            raise ValueError
    except (TypeError, ValueError):
        year = current_year
    rows = []
    months = yearly_totals(request.user, year)
    for month_number in range(1, 13):
        start = date(year, month_number, 1)
        rows.append({"month": start.strftime("%Y-%m"), "label": start.strftime("%B"),
                     "totals": months.get(month_number, money_totals({}))})
    totals = {key: sum((row["totals"][key] for row in rows), Decimal("0.00"))
              for key in money_totals({})}
    return render(request, "tracker/monthly_reports.html", {"year": year, "month": f"{year}-01",
                  "rows": rows, "year_totals": totals})


@login_required
def transactions(request):
    # Keep old bookmarks and their filters; there is only one monthly screen.
    params = request.GET.copy()
    if not params.get("kind"):
        params["kind"] = "all"
    return redirect(reverse("dashboard") + "?" + params.urlencode())


def inline_item(request, action, kind):
    """Validate and create workspace labels while serializing duplicate checks."""
    with transaction.atomic():
        lock_workspace(request.user)
        cls = CategoryForm if action == "category" else AccountForm
        form = cls(request.POST, owner=request.user, prefix=action)
        if action == "account" and kind == Entry.Kind.INCOME:
            form.fields["kind"].choices = [(Account.Kind.BANK, "Bank / UPI"), (Account.Kind.CASH, "Cash")]
        if form.is_valid():
            item = form.save()
            ChangeLog.objects.create(owner=request.user, action=f"{action}_created", object_label=str(item))
            return form, item
    return form, None


@login_required
def entry_form(request, kind=None, pk=None):
    context = chosen_month(request)
    entry = get_object_or_404(Entry, pk=pk, owner=request.user, voided_at__isnull=True) if pk else None
    kind = entry.kind if entry else kind
    if kind not in Entry.Kind.values:
        raise Http404
    before = entry_snapshot(entry) if entry else None
    product = None
    if kind == Entry.Kind.EXPENSE and request.GET.get("product"):
        try:
            product = get_object_or_404(Product, pk=request.GET["product"], owner=request.user, active=True)
        except (ValueError, TypeError) as exc:
            raise Http404 from exc
    preferences_key = f"entry_defaults_{request.user.pk}_{kind}"
    initial = dict(request.session.get(preferences_key, {})) if not entry else {}
    if not entry and not initial.get("account"):
        latest = Entry.objects.filter(owner=request.user, kind=kind, voided_at__isnull=True).order_by("-created_at").first()
        if latest:
            initial.update(account=latest.account_id)
            if kind == Entry.Kind.INCOME:
                initial["source"] = latest.source
        else:
            default_account = Account.objects.filter(owner=request.user, kind=Account.Kind.BANK).first()
            if default_account:
                initial["account"] = default_account.pk
    if product:
        initial["product"] = product.pk
    inline_action = request.POST.get("inline_action") if request.method == "POST" else None
    inline_form = None
    inline_saved = None
    if inline_action:
        if inline_action not in ("category", "account") or (inline_action == "category" and kind != Entry.Kind.EXPENSE):
            return HttpResponse("Invalid inline action", status=400)
        inline_form, inline_saved = inline_item(request, inline_action, kind)
        if request.headers.get("Accept") == "application/json":
            if inline_saved:
                return JsonResponse({"id": inline_saved.pk, "name": inline_saved.name,
                                     "kind": getattr(inline_saved, "kind", "")})
            return JsonResponse({"errors": inline_form.errors.get_json_data()}, status=400)
        # HTML fallback: rebuild the unfinished form without validating or saving it.
        initial = request.POST.dict()
        if inline_saved:
            initial[inline_action] = inline_saved.pk
            messages.success(request, f"{inline_saved.name} added and selected. Your entry is still unsaved.")
    form = EntryForm(request.POST if request.method == "POST" and not inline_action else None,
                     instance=entry, owner=request.user, kind=kind, initial=initial)
    if request.method == "POST" and not inline_action and form.is_valid():
        try:
            saved = save_entry(form, request.user, before)
        except ValidationError as exc:
            show_validation(form, exc)
        else:
            messages.success(request, "Entry saved.")
            target_month = saved.date.strftime("%Y-%m")
            request.session[preferences_key] = {name: getattr(saved, name + "_id") for name in ("account", "category") if name in form.fields}
            if kind == Entry.Kind.INCOME:
                request.session[preferences_key]["source"] = saved.source
            if "save_another" in request.POST and not entry:
                url = month_url("entry_add", target_month, kind=kind)
                if product:
                    url += f"&product={product.pk}"
                return redirect(url)
            if product:
                return redirect(month_url("product_detail", target_month, pk=product.pk))
            return redirect(month_url("dashboard", target_month) + f"&kind={kind}")
    account_form = AccountForm(owner=request.user, prefix="account")
    if kind == Entry.Kind.INCOME:
        account_form.fields["kind"].choices = [(Account.Kind.BANK, "Bank / UPI"), (Account.Kind.CASH, "Cash")]
    category_form = CategoryForm(owner=request.user, prefix="category")
    if inline_form and not inline_saved:
        if inline_action == "account":
            account_form = inline_form
        else:
            category_form = inline_form
    # Optional inline inputs must not block saving the main entry in the browser.
    for optional_form in (account_form, category_form):
        optional_form.use_required_attribute = False
    optional_fields = [form[n] for n in ("reference", "notes", "change_reason") if n in form.fields and not form.fields[n].required]
    context.update({"form": form, "title": ("Edit " if entry else "Add ") + Entry.Kind(kind).label.lower(),
                    "entry": entry, "entry_kind": kind, "product_context": product,
                    "cancel_url": month_url("product_detail", context["month"], pk=product.pk) if product else month_url("dashboard", context["month"]) + f"&kind={kind}",
                    "save_another": not entry, "account_form": account_form, "category_form": category_form,
                    "account_kinds": {str(a.pk): a.kind for a in form.fields["account"].queryset},
                    "optional_fields": optional_fields,
                    "optional_field_names": [field.name for field in optional_fields]})
    return render(request, "tracker/form.html", context)


@login_required
def entry_void(request, pk):
    entry = get_object_or_404(Entry, pk=pk, owner=request.user)
    form = DeleteEntryForm(request.POST or None, initial={"expected_revision": entry.revision})
    if request.method == "POST" and form.is_valid():
        try:
            void_entry(entry, request.user, reason="Deleted by user",
                       expected_revision=form.cleaned_data["expected_revision"], token=form.cleaned_data["submission_token"])
        except ValidationError as exc:
            show_validation(form, exc)
        else:
            messages.success(request, "Entry deleted.")
            return redirect(month_url("transactions", entry.date.strftime("%Y-%m")))
    context = chosen_month(request)
    return render(request, "tracker/confirm_void.html", {**context, "entry": entry, "form": form,
                  "cancel_url": month_url("dashboard", context["month"])})


@login_required
def products(request):
    context = chosen_month(request)
    rows = []
    balances = stock_totals(request.user, context["month_start"], context["month_end"])
    for product in Product.objects.filter(owner=request.user, active=True):
        rows.append({"product": product, **balances.get(product.pk, EMPTY_STOCK)})
    context["rows"] = rows
    return render(request, "tracker/products.html", context)


@login_required
def product_form(request, pk=None):
    context = chosen_month(request)
    product = get_object_or_404(Product, pk=pk, owner=request.user) if pk else None
    form = ProductForm(request.POST or None, request.FILES or None, instance=product, owner=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            lock_workspace(request.user)
            original = Product.objects.filter(pk=pk, owner=request.user).first() if pk else None
            if Product.objects.filter(owner=request.user, sku__iexact=form.cleaned_data["sku"]).exclude(pk=pk).exists():
                form.add_error("sku", "This SKU already exists in your workspace.")
            elif original and original.kind != form.cleaned_data["kind"] and original.movements.exists():
                form.add_error("kind", "Product type cannot change after stock is recorded; it would change historical sales statistics.")
            else:
                previous_photo = original.photo.name if original and original.photo else ""
                previous_storage = original.photo.storage if previous_photo else None
                product = form.save()
                if previous_photo and previous_photo != product.photo.name:
                    transaction.on_commit(lambda: previous_storage.delete(previous_photo))
                ChangeLog.objects.create(owner=request.user, action="product_saved", object_label=product.sku,
                                         details={"name": product.name, "kind": product.kind, "notes": product.notes})
                return redirect(month_url("product_detail", context["month"], pk=product.pk))
    context.update({"form": form, "title": "Edit SKU" if product else "Add a new SKU", "photo_product": product,
                    "save_label": "Save SKU", "cancel_url": month_url("products", context["month"])})
    return render(request, "tracker/form.html", context)


@login_required
def product_delete(request, pk):
    context = chosen_month(request)
    product = get_object_or_404(Product, pk=pk, owner=request.user)
    form = DeleteProductForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            lock_workspace(request.user)
            product = get_object_or_404(Product.objects.select_for_update(), pk=pk, owner=request.user)
            if product.active:
                product.active = False
                product.save(update_fields=["active"])
                ChangeLog.objects.create(owner=request.user, action="product_deleted", object_label=product.sku,
                                         details={"name": product.name, "kind": product.kind})
        messages.success(request, "SKU deleted.")
        return redirect(month_url("products", context["month"]))
    return render(request, "tracker/confirm_product_delete.html", {**context, "product": product, "form": form,
                  "cancel_url": month_url("products", context["month"])})


@login_required
def product_detail(request, pk):
    context = chosen_month(request)
    product = get_object_or_404(Product, pk=pk, owner=request.user)
    balances = stock_totals(request.user, context["month_start"], context["month_end"])
    context.update({"product": product, **balances.get(product.pk, EMPTY_STOCK),
                    "expenses": product.entries.filter(kind=Entry.Kind.EXPENSE, voided_at__isnull=True,
                        date__gte=context["month_start"], date__lt=context["month_end"]).select_related("account", "category", "product"),
                    "movements": product.movements.filter(reversal__isnull=True).order_by("-date", "-pk")})
    return render(request, "tracker/product_detail.html", context)


@login_required
def product_photo(request, pk):
    product = get_object_or_404(Product, pk=pk, owner=request.user)
    if not product.photo:
        raise Http404
    try:
        photo = product.photo.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    return FileResponse(photo, content_type="image/jpeg")


@login_required
def stock_edit(request, pk):
    movement = get_object_or_404(StockMovement, pk=pk, product__owner=request.user, reversal__isnull=True)
    context = chosen_month(request)
    form = StockEditForm(request.POST or None, instance=movement, owner=request.user,
                         initial={"expected_state": stock_state(movement)})
    if request.method == "POST" and form.is_valid():
        try:
            saved = edit_stock(movement, request.user, form.cleaned_data)
        except ValidationError as exc:
            show_validation(form, exc)
        else:
            messages.success(request, "Stock entry updated.")
            return redirect(month_url("product_detail", saved.date.strftime("%Y-%m"), pk=saved.product_id))
    optional_fields = [form[n] for n in ("batch_name", "notes")]
    return render(request, "tracker/form.html", {**context, "form": form,
        "title": f"Edit stock · {movement.product.name}", "save_label": "Save stock",
        "optional_fields": optional_fields, "optional_field_names": [field.name for field in optional_fields],
        "cancel_url": month_url("product_detail", context["month"], pk=movement.product_id)})


@login_required
def stock_delete(request, pk):
    movement = get_object_or_404(StockMovement, pk=pk, product__owner=request.user)
    context = chosen_month(request)
    form = DeleteStockForm(request.POST or None, initial={"expected_state": stock_state(movement)})
    if request.method == "POST" and form.is_valid():
        try:
            reverse_stock(movement, request.user, reason="Deleted by user",
                          token=form.cleaned_data["submission_token"], expected_state=form.cleaned_data["expected_state"])
        except ValidationError as exc:
            show_validation(form, exc)
        else:
            messages.success(request, "Stock entry deleted.")
            return redirect(month_url("product_detail", context["month"], pk=movement.product_id))
    return render(request, "tracker/confirm_stock_delete.html", {**context, "movement": movement, "form": form,
        "cancel_url": month_url("product_detail", context["month"], pk=movement.product_id)})


@login_required
def stock_form(request, pk):
    context = chosen_month(request)
    product = get_object_or_404(Product, pk=pk, owner=request.user, active=True)
    action = request.GET.get("action", "received")
    if action not in ("received", "sold"):
        raise Http404
    form = StockForm(request.POST or None, owner=request.user, action=action, product=product)
    if request.method == "POST" and form.is_valid():
        try:
            add_stock(product, request.user, form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Stock saved.")
            return redirect(month_url("product_detail", form.cleaned_data["date"].strftime("%Y-%m"), pk=pk))
    title = {"received": "Receive stock", "sold": "Record units sold"}[action]
    optional_fields = [form[n] for n in ("batch_name", "notes") if n in form.fields]
    context.update({"form": form, "title": f"{title} · {product.name}", "stock_form": True, "stock_action": action,
                    "save_label": {"received": "Receive stock", "sold": "Record units sold"}.get(action, "Save stock movement"),
                    "optional_fields": optional_fields,
                    "optional_field_names": [field.name for field in optional_fields],
                    "cancel_url": month_url("product_detail", context["month"], pk=pk)})
    return render(request, "tracker/form.html", context)


@login_required
def workspace_settings(request):
    account_form = AccountForm(owner=request.user, prefix="account")
    category_form = CategoryForm(owner=request.user, prefix="category")
    if request.method == "POST":
        action = request.POST.get("action")
        form = None
        if action == "account":
            account_form = form = AccountForm(request.POST, owner=request.user, prefix="account")
        elif action == "category":
            category_form = form = CategoryForm(request.POST, owner=request.user, prefix="category")
        if form:
            with transaction.atomic():
                lock_workspace(request.user)
                if form.is_valid():
                    item = form.save()
                    ChangeLog.objects.create(owner=request.user, action=f"{action}_created", object_label=str(item))
                    messages.success(request, "Saved. It will be available in every month.")
                    return redirect("settings")
    return render(request, "tracker/settings.html", {"account_form": account_form, "category_form": category_form,
                  "accounts": Account.objects.filter(owner=request.user), "categories": Category.objects.filter(owner=request.user)})


@login_required
def history(request):
    logs = ChangeLog.objects.filter(owner=request.user)
    entry_id = request.GET.get("entry")
    if entry_id:
        entry = get_object_or_404(Entry, owner=request.user, pk=entry_id)
        logs = logs.filter(object_label=f"Transaction #{entry.pk}")
    page = Paginator(logs, 50).get_page(request.GET.get("page"))
    return render(request, "tracker/history.html", {"page": page, "entry_id": entry_id or ""})


@login_required
def export_csv(request):
    context = chosen_month(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="transactions-{context["month"]}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["ID", "Date", "Entry", "Amount INR", "Account", "Source", "Category", "SKU", "Paid by", "Destination", "Reference", "Notes"])
    for entry in monthly_entries(request.user, context["month_start"], context["month_end"]):
        writer.writerow([entry.pk, entry.date.isoformat(), entry.get_kind_display(), str(entry.amount),
                         *[safe_csv_cell(value) for value in (entry.account.name, entry.get_source_display(), entry.category,
                            entry.product.sku if entry.product else "",
                            entry.paid_by, entry.destination, entry.reference, entry.notes)]])
    return response


@login_required
@require_safe
def bank_tally(request):
    context = chosen_month(request)
    accounts = Account.objects.filter(owner=request.user)
    requested_account = request.GET.get("account")
    if requested_account:
        try:
            get_object_or_404(accounts, pk=requested_account)
        except (ValueError, TypeError) as exc:
            raise Http404 from exc
    context.update(payment_totals(request.user, context["month_start"], context["month_end"]))
    return render(request, "tracker/bank_tally.html", context)


@login_required
def stock_reverse(request, pk):
    movement = get_object_or_404(StockMovement, pk=pk, product__owner=request.user)
    form = ConfirmChangeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            reverse_stock(movement, request.user, reason=form.cleaned_data["reason"], token=form.cleaned_data["submission_token"])
        except ValidationError as exc:
            show_validation(form, exc)
        else:
            messages.success(request, "Movement reversed in its original month. History is preserved; enter the corrected movement next.")
            return redirect(month_url("product_detail", movement.date.strftime("%Y-%m"), pk=movement.product_id))
    context = chosen_month(request)
    return render(request, "tracker/confirm_stock.html", {**context, "form": form, "movement": movement,
                  "cancel_url": month_url("product_detail", context["month"], pk=movement.product_id)})


@login_required
def month_review(request):
    context = chosen_month(request)
    review = MonthReview.objects.filter(owner=request.user, month=context["month_start"]).first()
    form = MonthReviewForm(request.POST or None, initial={"expected_state": str(review.revision if review else 0)})
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action")
        if action not in ("close", "reopen"):
            form.add_error(None, "Choose a valid review action.")
        else:
            try:
                change_month(request.user, context["month"], close=action == "close", reason=form.cleaned_data["reason"],
                             expected_state=form.cleaned_data["expected_state"], token=form.cleaned_data["submission_token"])
            except ValidationError as exc:
                show_validation(form, exc)
            else:
                messages.success(request, "Month closed." if action == "close" else "Month reopened. Your reason was saved.")
                return redirect(month_url("month_review", context["month"]))
    context["totals"] = monthly_totals(request.user, context["month_start"], context["month_end"])
    context.update({"form": form, "review": review})
    return render(request, "tracker/month_review.html", context)


def health(request):
    """No user, configuration, account or exception details in health responses."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return HttpResponse("unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
