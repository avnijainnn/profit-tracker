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
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .domain import safe_csv_cell
from .forms import AccountForm, BankTallyForm, CategoryForm, EntryForm, ProductForm, StockForm, ConfirmChangeForm, MonthReviewForm
from .models import Account, BankTally, Category, ChangeLog, Entry, Product, StockMovement, MonthReview
from .services import add_stock, bank_activity, chosen_month, entry_snapshot, monthly_entries, product_stats, report, save_bank_tally, save_entry, setup_defaults, void_entry, reverse_stock, change_month
from .guards import lock_workspace


def show_validation(form, exc):
    for message in exc.messages:
        form.add_error(None, message)


def month_url(name, month, **kwargs):
    return reverse(name, kwargs=kwargs) + f"?month={month}"


@login_required
def dashboard(request):
    context = chosen_month(request)
    context.update(report(request.user, context["month_start"], context["month_end"]))
    context["has_accounts"] = Account.objects.filter(owner=request.user).exists()
    context["review"] = MonthReview.objects.filter(owner=request.user, month=context["month_start"]).first()
    entries = monthly_entries(request.user, context["month_start"], context["month_end"])
    kind = request.GET.get("kind", "income")
    if kind not in Entry.Kind.values and kind != "all":
        kind = "income"
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
    for month_number in range(1, 13):
        start = date(year, month_number, 1)
        end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)
        month_report = report(request.user, start, end)
        rows.append({"month": start.strftime("%Y-%m"), "label": start.strftime("%B"), **month_report})
    totals = {key: sum((row["totals"][key] for row in rows), Decimal("0.00"))
              for key in ("income", "expense", "result", "withdrawal", "after_withdrawals", "cash_profit",
                          "operating_income", "operating_expense", "cogs", "inventory_writeoff", "operating_profit")}
    totals["unrecognized_receipts"] = sum(row["totals"]["unrecognized_receipts"] for row in rows)
    totals["cogs_unknown_units"] = sum(row["totals"]["cogs_unknown_units"] for row in rows)
    totals["writeoff_unknown_units"] = sum(row["totals"]["writeoff_unknown_units"] for row in rows)
    totals["sold_bags"] = sum(row["sold_bags"] for row in rows)
    totals["sold_thrift"] = sum(row["sold_thrift"] for row in rows)
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
        product = get_object_or_404(Product, pk=request.GET["product"], owner=request.user)
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
    optional_fields = [form[n] for n in ("reference", "notes") if n in form.fields and not form.fields[n].required]
    context.update({"form": form, "title": ("Edit " if entry else "Add ") + ("revenue" if kind == "income" else Entry.Kind(kind).label.lower()),
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
    form = ConfirmChangeForm(request.POST or None, initial={"expected_revision": entry.revision})
    if request.method == "POST" and form.is_valid():
        try:
            void_entry(entry, request.user, reason=form.cleaned_data["reason"],
                       expected_revision=form.cleaned_data["expected_revision"], token=form.cleaned_data["submission_token"])
        except ValidationError as exc:
            show_validation(form, exc)
        else:
            messages.success(request, "Entry voided; the original and your reason remain in history.")
            return redirect(month_url("transactions", entry.date.strftime("%Y-%m")))
    context = chosen_month(request)
    return render(request, "tracker/confirm_void.html", {**context, "entry": entry, "form": form,
                  "cancel_url": month_url("entry_edit", context["month"], pk=entry.pk)})


@login_required
def products(request):
    context = chosen_month(request)
    rows = []
    for product in Product.objects.filter(owner=request.user).prefetch_related("movements", "entries"):
        rows.append({"product": product, **product_stats(product, context["month_start"], context["month_end"])})
    context["rows"] = rows
    return render(request, "tracker/products.html", context)


@login_required
def product_form(request, pk=None):
    context = chosen_month(request)
    product = get_object_or_404(Product, pk=pk, owner=request.user) if pk else None
    form = ProductForm(request.POST or None, instance=product, owner=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            lock_workspace(request.user)
            original = Product.objects.filter(pk=pk, owner=request.user).first() if pk else None
            if original and original.kind != form.cleaned_data["kind"] and original.movements.exists():
                form.add_error("kind", "Product type cannot change after stock is recorded; it would change historical sales statistics.")
            else:
                product = form.save()
                ChangeLog.objects.create(owner=request.user, action="product_saved", object_label=product.sku,
                                         details={"name": product.name, "kind": product.kind, "notes": product.notes})
                return redirect(month_url("product_detail", context["month"], pk=product.pk))
    context.update({"form": form, "title": "Edit SKU" if product else "Add a new SKU", "save_label": "Save SKU", "cancel_url": month_url("products", context["month"])})
    return render(request, "tracker/form.html", context)


@login_required
def product_detail(request, pk):
    context = chosen_month(request)
    product = get_object_or_404(Product, pk=pk, owner=request.user)
    context.update({"product": product, **product_stats(product, context["month_start"], context["month_end"]),
                    "expenses": product.entries.filter(kind=Entry.Kind.EXPENSE, voided_at__isnull=True,
                                                       capitalized_inventory_cost=False).select_related("account", "category"),
                    "movements": product.movements.select_related("reversal").prefetch_related("lot_depletions__lot").order_by("-date", "-pk")})
    return render(request, "tracker/product_detail.html", context)


@login_required
def stock_form(request, pk):
    context = chosen_month(request)
    product = get_object_or_404(Product, pk=pk, owner=request.user)
    action = request.GET.get("action")
    if action not in (None, "received", "sold", "more"):
        raise Http404
    form = StockForm(request.POST or None, owner=request.user, action=action, product=product)
    if request.method == "POST" and form.is_valid():
        try:
            add_stock(product, request.user, form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Stock movement and FIFO lot cost saved.")
            return redirect(month_url("product_detail", form.cleaned_data["date"].strftime("%Y-%m"), pk=pk))
    title = {"received": "Receive stock", "sold": "Record units sold"}.get(action, "More stock actions")
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
        if action == "defaults":
            setup_defaults(request.user)
            messages.success(request, "Default accounts and categories added. Existing items were kept.")
            return redirect("settings")
        form = None
        if action == "account":
            account_form = form = AccountForm(request.POST, owner=request.user, prefix="account")
        elif action == "category":
            category_form = form = CategoryForm(request.POST, owner=request.user, prefix="category")
        if form and form.is_valid():
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
    writer.writerow(["ID", "Cash date", "Sale date", "Kind", "Cash amount INR", "Recognized sales INR", "Account", "Source", "Category", "Subcategory", "SKU", "Cost behavior", "Paid by", "Destination", "Reference", "Notes"])
    for entry in monthly_entries(request.user, context["month_start"], context["month_end"]):
        writer.writerow([entry.pk, entry.date.isoformat(), entry.sale_date.isoformat() if entry.sale_date else "",
                         entry.get_kind_display(), str(entry.amount), str(entry.recognized_amount or ""),
                         *[safe_csv_cell(value) for value in (entry.account.name, entry.get_source_display(), entry.category,
                            entry.subcategory, entry.product.sku if entry.product else "", entry.cost_behavior,
                            entry.paid_by, entry.destination, entry.reference, entry.notes)]])
    return response


@login_required
def bank_tally(request):
    context = chosen_month(request)
    accounts = Account.objects.filter(owner=request.user).exclude(kind=Account.Kind.OTHER)
    requested_account = request.POST.get("account") if request.method == "POST" else request.GET.get("account")
    if requested_account:
        account = get_object_or_404(accounts, pk=requested_account)
    else:
        account = accounts.first()
    rows = []
    for bank_account in accounts:
        tally = BankTally.objects.filter(owner=request.user, account=bank_account, month=context["month_start"]).first()
        activity = bank_activity(request.user, bank_account, context["month_start"], context["month_end"])
        rows.append({"account": bank_account, "tally": tally, "activity": activity,
                     "credit_difference": tally.statement_credits - activity["credits"] if tally else None,
                     "debit_difference": tally.statement_debits - activity["debits"] if tally else None})
    form = None
    selected_tally = None
    if account:
        selected_tally = BankTally.objects.filter(owner=request.user, account=account, month=context["month_start"]).first()
        if request.method == "POST":
            form = BankTallyForm(request.POST)
            if form.is_valid():
                try:
                    save_bank_tally(request.user, account, context["month_start"], form.cleaned_data)
                except ValidationError as exc:
                    show_validation(form, exc)
                else:
                    messages.success(request, "Statement totals saved. Compare the differences below with your statement.")
                    return redirect(f"{reverse('bank_tally')}?month={context['month']}&account={account.pk}#edit-tally")
        else:
            form = BankTallyForm(initial={
                "statement_credits": selected_tally.statement_credits if selected_tally else Decimal("0.00"),
                "statement_debits": selected_tally.statement_debits if selected_tally else Decimal("0.00"),
                "notes": selected_tally.notes if selected_tally else "",
                "expected_revision": selected_tally.revision if selected_tally else 0,
            })
    context.update({"accounts": accounts, "rows": rows, "selected_account": account,
                    "selected_tally": selected_tally, "form": form,
                    "selected_activity": bank_activity(request.user, account, context["month_start"], context["month_end"]) if account else None})
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
    context.update(report(request.user, context["month_start"], context["month_end"]))
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
