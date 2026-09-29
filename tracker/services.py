from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace
import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from .domain import month_bounds, statement_summary, stock_delta, validate_stock_timeline
from .models import Account, BankTally, Category, ChangeLog, Entry, Product, StockMovement, StockReversal, MonthReview, InventoryLot, LotDepletion
from .guards import lock_workspace, fingerprint, prior_submission, record_submission, require_open_months


def chosen_month(request):
    # On the 1st, reviewing last month is the natural default.
    from datetime import timedelta
    today = timezone.localdate()
    default = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    value = request.GET.get("month") or request.session.get("review_month", default)
    try:
        start, end = month_bounds(value)
    except (ValueError, OverflowError):
        value = default
        start, end = month_bounds(value)
    if request.session.get("review_month") != value:
        request.session["review_month"] = value
    return {"month": value, "month_start": start, "month_end": end, "month_label": start.strftime("%B %Y")}


def monthly_entries(owner, start, end):
    return Entry.objects.filter(owner=owner, date__gte=start, date__lt=end, voided_at__isnull=True).select_related("account", "category", "product", "destination")


def report(owner, start, end):
    entries = list(monthly_entries(owner, start, end))
    totals = statement_summary(entries)
    # Cash Profit follows actual money dates. Operating Profit follows sale dates
    # and FIFO COGS, with inventory purchases excluded from operating expenses.
    sale_income = Entry.objects.filter(owner=owner, kind=Entry.Kind.INCOME, voided_at__isnull=True,
                                       sale_date__gte=start, sale_date__lt=end)
    operating_income = sale_income.aggregate(value=Sum("recognized_amount"))["value"] or Decimal("0.00")
    unrecognized_receipts = Entry.objects.filter(owner=owner, kind=Entry.Kind.INCOME, voided_at__isnull=True,
        recognized_amount__isnull=True).filter(Q(date__gte=start, date__lt=end) |
                                               Q(sale_date__gte=start, sale_date__lt=end)).count()
    operating_expense = Entry.objects.filter(owner=owner, kind=Entry.Kind.EXPENSE, voided_at__isnull=True,
        date__gte=start, date__lt=end, capitalized_inventory_cost=False).aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    cash_expense = Entry.objects.filter(owner=owner, kind=Entry.Kind.EXPENSE, voided_at__isnull=True,
        date__gte=start, date__lt=end).exclude(account__kind=Account.Kind.OTHER).aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    cogs = sum((d.unit_cost * d.quantity for d in LotDepletion.objects.filter(
        movement__date__gte=start, movement__date__lt=end, movement__kind=StockMovement.Kind.SOLD,
        movement__reversal__isnull=True, lot__owner=owner)), Decimal("0.00")).quantize(Decimal("0.01"))
    stock_writeoff = sum((d.unit_cost * d.quantity for d in LotDepletion.objects.filter(
        movement__date__gte=start, movement__date__lt=end,
        movement__kind__in=[StockMovement.Kind.DAMAGED, StockMovement.Kind.ADJUST_OUT],
        movement__reversal__isnull=True, lot__owner=owner)), Decimal("0.00")).quantize(Decimal("0.01"))
    unknown_cogs_units = sum(d.quantity for d in LotDepletion.objects.filter(
        movement__date__gte=start, movement__date__lt=end, movement__kind=StockMovement.Kind.SOLD,
        movement__reversal__isnull=True, lot__owner=owner, lot__costs_confirmed=False))
    unknown_writeoff_units = sum(d.quantity for d in LotDepletion.objects.filter(
        movement__date__gte=start, movement__date__lt=end,
        movement__kind__in=[StockMovement.Kind.DAMAGED, StockMovement.Kind.ADJUST_OUT],
        movement__reversal__isnull=True, lot__owner=owner, lot__costs_confirmed=False))
    totals.update(cash_expense=cash_expense, cash_profit=totals["income"] - cash_expense,
                  operating_income=operating_income,
                  operating_expense=operating_expense, cogs=cogs,
                  operating_profit=operating_income - operating_expense - cogs - stock_writeoff,
                  inventory_writeoff=stock_writeoff,
                  cogs_unknown_units=unknown_cogs_units, writeoff_unknown_units=unknown_writeoff_units,
                  unrecognized_receipts=unrecognized_receipts)
    sources = defaultdict(lambda: Decimal("0.00"))
    categories = defaultdict(lambda: Decimal("0.00"))
    cost_behaviors = defaultdict(lambda: Decimal("0.00"))
    third_party = Decimal("0.00")
    for entry in entries:
        if entry.kind == Entry.Kind.INCOME:
            sources[entry.get_source_display()] += entry.amount
        elif entry.kind == Entry.Kind.EXPENSE:
            categories[entry.category.name] += entry.amount
            cost_behaviors[entry.get_cost_behavior_display()] += entry.amount
            if entry.account.kind == Account.Kind.OTHER:
                third_party += entry.amount
    movements = StockMovement.objects.filter(product__owner=owner, date__gte=start, date__lt=end, reversal__isnull=True)
    sold_bags = movements.filter(kind="sold", product__kind="bag").aggregate(value=Sum("quantity"))["value"] or 0
    sold_thrift = movements.filter(kind="sold", product__kind="thrift").aggregate(value=Sum("quantity"))["value"] or 0
    returned = movements.filter(kind="returned").aggregate(value=Sum("quantity"))["value"] or 0
    sku_sales_total = movements.filter(kind="sold").aggregate(value=Sum("sales_amount"))["value"] or Decimal("0.00")
    return {"totals": totals, "sources": sorted(sources.items()), "categories": sorted(categories.items(), key=lambda x: x[1], reverse=True),
            "cost_behaviors": sorted(cost_behaviors.items(), key=lambda x: x[1], reverse=True),
            "third_party": third_party, "sold_bags": sold_bags, "sold_thrift": sold_thrift, "returned": returned,
            "sku_sales_total": sku_sales_total, "recent_entries": entries[:6], "entry_count": len(entries)}


def entry_snapshot(entry):
    return {field: str(getattr(entry, field) or "") for field in (
        "id", "date", "sale_date", "recognized_amount", "kind", "amount", "account_id", "destination_id", "source",
        "category_id", "subcategory_id", "cost_behavior", "product_id", "inventory_lot_id",
        "capitalized_inventory_cost", "paid_by", "reference", "notes", "voided_at",
    )}


@transaction.atomic
def save_entry(form, owner, before=None):
    lock_workspace(owner)
    entry = form.save(commit=False)
    entry.owner = owner
    if entry.kind == Entry.Kind.EXPENSE and (not entry.pk or not before or
            before.get("category_id") != str(entry.category_id or "") or
            before.get("subcategory_id") != str(entry.subcategory_id or "")):
        selected = form.cleaned_data.get("subcategory") or form.cleaned_data.get("category")
        if selected:
            entry.cost_behavior = selected.default_cost_behavior
    token = form.cleaned_data["submission_token"]
    payload = entry_snapshot(entry)
    payload["revision"] = form.cleaned_data["expected_revision"]
    payload["reason"] = form.cleaned_data.get("change_reason", "")
    payload["amount"] = format(entry.amount, ".2f")
    digest = fingerprint("save_entry", payload)
    prior = prior_submission(owner, token, digest)
    if prior:
        return Entry.objects.get(pk=prior, owner=owner)
    before = None
    if entry.pk:
        existing = Entry.objects.get(pk=entry.pk, owner=owner)
        if existing.voided_at or existing.revision != form.cleaned_data["expected_revision"]:
            raise ValidationError("This entry changed since you opened it. Refresh before editing.")
        if existing.capitalized_inventory_cost:
            raise ValidationError("This payment is attached to an inventory lot. Reverse the stock receipt before changing it.")
        if not payload["reason"].strip():
            raise ValidationError("A correction reason is required.")
        require_open_months(owner, existing.date, entry.date, *([existing.sale_date] if existing.sale_date else []),
                            *([entry.sale_date] if entry.sale_date else []))
        before = entry_snapshot(existing)
        entry.revision = existing.revision + 1
    else:
        require_open_months(owner, entry.date, *([entry.sale_date] if entry.sale_date else []))
    if entry.reference and Entry.objects.filter(owner=owner, account=entry.account, reference=entry.reference,
            voided_at__isnull=True).exclude(pk=entry.pk).exists():
        raise ValidationError("This statement reference already exists for this account. Check for a duplicate.")
    entry.full_clean()
    entry.save()
    ChangeLog.objects.create(owner=owner, action="entry_updated" if before else "entry_created",
                             object_label=f"Transaction #{entry.pk}", details={"before": before, "after": entry_snapshot(entry), "reason": payload["reason"]})
    record_submission(owner, token, digest, entry.pk)
    return entry


@transaction.atomic
def void_entry(entry, owner, *, reason, expected_revision, token):
    lock_workspace(owner)
    digest = fingerprint("void_entry", {"id": entry.pk, "revision": expected_revision, "reason": reason})
    if prior_submission(owner, token, digest):
        return
    entry = Entry.objects.get(pk=entry.pk, owner=owner)
    if entry.capitalized_inventory_cost:
        raise ValidationError("This payment is attached to an inventory lot. Reverse the stock receipt before voiding it.")
    if entry.voided_at or entry.revision != expected_revision:
        raise ValidationError("This entry changed. Refresh and review the latest version.")
    if not reason.strip():
        raise ValidationError("A reason is required.")
    require_open_months(owner, entry.date, *([entry.sale_date] if entry.sale_date else []))
    before = entry_snapshot(entry)
    entry.voided_at = timezone.now()
    entry.revision += 1
    entry.save(update_fields=["voided_at", "updated_at", "revision"])
    ChangeLog.objects.create(owner=owner, action="entry_voided", object_label=f"Transaction #{entry.pk}", details={"before": before, "reason": reason})
    record_submission(owner, token, digest, entry.pk)


@transaction.atomic
def add_stock(product, owner, cleaned_data):
    lock_workspace(owner)
    product = Product.objects.select_for_update().get(pk=product.pk, owner=owner)
    values = dict(cleaned_data)
    receipt_fields = {name: values.pop(name, None) for name in (
        "payment_date", "manufacturer", "manufacturing_cost", "base_shipping_cost",
        "extra_shipping_cost", "other_direct_cost", "payment_account", "costs_confirmed", "existing_cost_entries")}
    token = values.pop("submission_token", None) or uuid.uuid4()
    selected_ids = sorted({entry.pk for entry in (receipt_fields["existing_cost_entries"] or [])})
    receipt_payload = {**receipt_fields,
                       "payment_account": getattr(receipt_fields["payment_account"], "pk", None),
                       "existing_cost_entries": selected_ids}
    digest = fingerprint("add_stock", {"product": product.pk, **values, **receipt_payload})
    prior = prior_submission(owner, token, digest)
    if prior:
        return StockMovement.objects.get(pk=prior, product=product)
    movement = StockMovement(product=product, **values)
    movement.full_clean()
    require_open_months(owner, movement.date, inventory=True)
    if receipt_fields["payment_date"]:
        require_open_months(owner, receipt_fields["payment_date"])
    existing = list(product.movements.filter(reversal__isnull=True).order_by("date", "pk"))
    candidate = SimpleNamespace(date=movement.date, kind=movement.kind, quantity=movement.quantity, pk=float("inf"))
    timeline = sorted([*existing, candidate], key=lambda item: (item.date, item.pk))
    try:
        validate_stock_timeline(timeline)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    lot = None
    if movement.kind == StockMovement.Kind.RECEIVED:
        # Re-read under the workspace lock: an earlier form may hold stale objects.
        selected_costs = list(Entry.objects.select_for_update(of=("self",)).filter(
            pk__in=selected_ids, owner=owner).select_related("category").order_by("pk"))
        if len(selected_costs) != len(selected_ids):
            raise ValidationError("Choose only active, unassigned expenses for this product.")
        component_totals = {"manufacturing_cost": receipt_fields["manufacturing_cost"] or Decimal("0.00"),
                            "base_shipping_cost": receipt_fields["base_shipping_cost"] or Decimal("0.00"),
                            "extra_shipping_cost": receipt_fields["extra_shipping_cost"] or Decimal("0.00"),
                            "other_direct_cost": receipt_fields["other_direct_cost"] or Decimal("0.00")}
        for entry in selected_costs:
            if entry.owner_id != owner.pk or entry.product_id != product.pk or entry.kind != Entry.Kind.EXPENSE \
                    or entry.inventory_lot_id or entry.capitalized_inventory_cost or entry.voided_at:
                raise ValidationError("Choose only active, unassigned expenses for this product.")
            require_open_months(owner, entry.date)
            category_name = (entry.category.name if entry.category_id else "").casefold()
            component = "manufacturing_cost" if "manufactur" in category_name else (
                "base_shipping_cost" if "shipping" in category_name else "other_direct_cost")
            component_totals[component] += entry.amount
        lot = InventoryLot(owner=owner, product=product, received_date=movement.date,
            quantity_received=movement.quantity, batch_name=movement.batch_name,
            manufacturer=receipt_fields["manufacturer"] or "",
            manufacturing_cost=component_totals["manufacturing_cost"],
            base_shipping_cost=component_totals["base_shipping_cost"],
            extra_shipping_cost=component_totals["extra_shipping_cost"],
            other_direct_cost=component_totals["other_direct_cost"],
            costs_confirmed=bool(receipt_fields["costs_confirmed"]))
        lot.full_clean()
        lot.save()
        movement.inventory_lot = lot
    elif movement.kind in (StockMovement.Kind.RETURNED, StockMovement.Kind.ADJUST_IN):
        lot = InventoryLot(owner=owner, product=product, received_date=movement.date,
            quantity_received=movement.quantity, batch_name=movement.batch_name or movement.get_kind_display(),
            costs_confirmed=False)
        lot.full_clean()
        lot.save()
        movement.inventory_lot = lot
    movement.save()
    for linked_entry in (selected_costs if movement.kind == StockMovement.Kind.RECEIVED else []):
        before_cost = entry_snapshot(linked_entry)
        linked_entry.inventory_lot = lot
        linked_entry.capitalized_inventory_cost = True
        linked_entry.revision += 1
        linked_entry.full_clean()
        linked_entry.save(update_fields=["inventory_lot", "capitalized_inventory_cost", "revision", "updated_at"])
        ChangeLog.objects.create(owner=owner, action="inventory_cost_linked", object_label=f"Transaction #{linked_entry.pk}",
            details={"before": before_cost, "after": entry_snapshot(linked_entry), "inventory_lot": lot.pk})
    if movement.kind == StockMovement.Kind.RECEIVED and lot and lot.landed_cost:
        account = receipt_fields["payment_account"]
        payment_date = receipt_fields["payment_date"] or movement.date
        component_categories = (("manufacturing_cost", "Manufacturing"),
                                ("base_shipping_cost", "Shipping & transit"),
                                ("extra_shipping_cost", "Shipping & transit"),
                                ("other_direct_cost", "General"))
        for field, category_name in component_categories:
            amount = receipt_fields[field] or Decimal("0.00")
            if not amount:
                continue
            category, _ = Category.objects.get_or_create(owner=owner, name=category_name)
            expense = Entry(owner=owner, kind=Entry.Kind.EXPENSE, date=payment_date, amount=amount,
                account=account, category=category, product=product, inventory_lot=lot,
                capitalized_inventory_cost=True, cost_behavior=Category.CostBehavior.INVENTORY,
                notes=f"Stock lot {lot.batch_name or lot.pk}: {category_name.lower()} cost")
            expense.full_clean()
            expense.save()
            ChangeLog.objects.create(owner=owner, action="entry_created", object_label=f"Stock lot expense #{expense.pk}",
                details={"after": entry_snapshot(expense), "inventory_lot": lot.pk})
    recompute_lot_depletions(product)
    ChangeLog.objects.create(owner=owner, action="stock_recorded", object_label=f"{product.sku} · movement #{movement.pk}",
                             details={"date": str(movement.date), "kind": movement.kind, "quantity": movement.quantity,
                                      "batch": movement.batch_name, "notes": movement.notes})
    record_submission(owner, token, digest, movement.pk)
    return movement


def recompute_lot_depletions(product):
    """Rebuild derived FIFO allocation after a valid stock timeline change."""
    LotDepletion.objects.filter(movement__product=product).delete()
    remaining = {}
    lots = {}
    for movement in product.movements.filter(reversal__isnull=True).select_related("inventory_lot").order_by("date", "pk"):
        if movement.kind in (StockMovement.Kind.RECEIVED, StockMovement.Kind.RETURNED, StockMovement.Kind.ADJUST_IN):
            lot = movement.inventory_lot
            if lot:
                remaining[lot.pk] = lot.quantity_received
                lots[lot.pk] = lot
        elif movement.kind == StockMovement.Kind.SOLD:
            needed = movement.quantity
            for lot in sorted(lots.values(), key=lambda item: (item.received_date, item.pk)):
                available = remaining.get(lot.pk, 0)
                take = min(needed, available)
                if take:
                    LotDepletion.objects.create(movement=movement, lot=lot, quantity=take,
                                                unit_cost=lot.landed_cost_per_unit)
                    remaining[lot.pk] -= take
                    needed -= take
                if not needed:
                    break
            if needed:
                raise ValidationError("FIFO allocation could not find enough received stock.")
        elif movement.kind in (StockMovement.Kind.DAMAGED, StockMovement.Kind.ADJUST_OUT):
            needed = movement.quantity
            for lot in sorted(lots.values(), key=lambda item: (item.received_date, item.pk)):
                take = min(needed, remaining.get(lot.pk, 0))
                if take:
                    LotDepletion.objects.create(movement=movement, lot=lot, quantity=take,
                                                unit_cost=lot.landed_cost_per_unit)
                remaining[lot.pk] -= take
                needed -= take
                if not needed:
                    break


def product_stats(product, start, end):
    movements = list(product.movements.filter(reversal__isnull=True).order_by("date", "pk"))
    cash_expenses = product.entries.filter(kind=Entry.Kind.EXPENSE, voided_at__isnull=True)
    expenses = cash_expenses.filter(capitalized_inventory_cost=False)
    by_month = defaultdict(lambda: Decimal("0.00"))
    for expense in expenses:
        by_month[expense.date.strftime("%Y-%m")] += expense.amount
    cash_by_month = defaultdict(lambda: Decimal("0.00"))
    for expense in cash_expenses:
        cash_by_month[expense.date.strftime("%Y-%m")] += expense.amount
    lot_rows = []
    live_lots = list(product.lots.filter(movements__reversal__isnull=True).distinct().order_by("received_date", "pk"))
    available_by_lot = {lot.pk: lot.quantity_received for lot in live_lots}
    for movement in movements:
        if movement.kind == StockMovement.Kind.SOLD:
            for depletion in movement.lot_depletions.select_related("lot").all():
                available_by_lot[depletion.lot_id] = max(0, available_by_lot.get(depletion.lot_id, 0) - depletion.quantity)
        elif movement.kind in (StockMovement.Kind.DAMAGED, StockMovement.Kind.ADJUST_OUT):
            needed = movement.quantity
            for lot in live_lots:
                take = min(needed, available_by_lot.get(lot.pk, 0))
                available_by_lot[lot.pk] -= take
                needed -= take
                if not needed:
                    break
    for lot in live_lots:
        allocations = LotDepletion.objects.filter(lot=lot, movement__kind=StockMovement.Kind.SOLD)
        lot_rows.append({"lot": lot, "remaining": available_by_lot.get(lot.pk, 0),
                         "extra_and_other_cost": lot.extra_shipping_cost + lot.other_direct_cost,
                         "units_sold": allocations.aggregate(value=Sum("quantity"))["value"] or 0,
                         "cogs": sum((d.unit_cost * d.quantity for d in allocations), Decimal("0.00")).quantize(Decimal("0.01"))})
    return {
        "available": sum(stock_delta(m.kind, m.quantity) for m in movements),
        "stock_at_month_end": sum(stock_delta(m.kind, m.quantity) for m in movements if m.date < end),
        "received": sum(m.quantity for m in movements if m.kind == "received"),
        "month_sold": sum(m.quantity for m in movements if m.kind == "sold" and start <= m.date < end),
        "sales_total": sum((m.sales_amount or Decimal("0.00")) for m in movements if m.kind == "sold"),
        "month_sales": sum((m.sales_amount or Decimal("0.00")) for m in movements
                   if m.kind == "sold" and start <= m.date < end),
        "spent": sum(cash_by_month.values(), Decimal("0.00")),
        "month_spent": cash_by_month.get(start.strftime("%Y-%m"), Decimal("0.00")),
        "cost_months": sorted(by_month.items(), reverse=True),
        "lots": lot_rows,
        "month_cogs": sum((d.unit_cost * d.quantity for d in LotDepletion.objects.filter(
            lot__product=product, movement__kind=StockMovement.Kind.SOLD, movement__date__gte=start, movement__date__lt=end,
            movement__reversal__isnull=True)), Decimal("0.00")).quantize(Decimal("0.01")),
    }


def bank_activity(owner, account, start, end):
    entries = Entry.objects.filter(owner=owner, date__gte=start, date__lt=end, voided_at__isnull=True)
    credits = entries.filter(kind=Entry.Kind.INCOME, account=account).aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    credits += entries.filter(kind=Entry.Kind.TRANSFER, destination=account).aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    debits = entries.filter(account=account, kind__in=[Entry.Kind.EXPENSE, Entry.Kind.TRANSFER,
                                                        Entry.Kind.WITHDRAWAL]).aggregate(value=Sum("amount"))["value"] or Decimal("0.00")
    return {"credits": credits, "debits": debits}


@transaction.atomic
def save_bank_tally(owner, account, month, cleaned_data):
    lock_workspace(owner)
    account = Account.objects.select_for_update().filter(pk=account.pk, owner=owner).exclude(kind=Account.Kind.OTHER).get()
    token = cleaned_data["submission_token"]
    payload = {
        "account": account.pk,
        "month": month,
        "statement_credits": format(cleaned_data["statement_credits"], ".2f"),
        "statement_debits": format(cleaned_data["statement_debits"], ".2f"),
        "notes": cleaned_data["notes"],
        "revision": cleaned_data["expected_revision"],
    }
    digest = fingerprint("save_bank_tally", payload)
    prior = prior_submission(owner, token, digest)
    if prior:
        return BankTally.objects.get(pk=prior, owner=owner)
    require_open_months(owner, month)
    tally = BankTally.objects.select_for_update().filter(owner=owner, account=account, month=month).first()
    if tally and tally.revision != cleaned_data["expected_revision"]:
        raise ValidationError("This bank tally changed since you opened it. Refresh before saving.")
    if not tally and cleaned_data["expected_revision"] != 0:
        raise ValidationError("This bank tally no longer exists. Refresh before saving.")
    before = None
    if tally:
        before = {"statement_credits": str(tally.statement_credits), "statement_debits": str(tally.statement_debits),
                  "notes": tally.notes, "revision": tally.revision}
        tally.revision += 1
    else:
        tally = BankTally(owner=owner, account=account, month=month)
    tally.statement_credits = cleaned_data["statement_credits"]
    tally.statement_debits = cleaned_data["statement_debits"]
    tally.notes = cleaned_data["notes"]
    tally.full_clean()
    tally.save()
    after = {"statement_credits": str(tally.statement_credits), "statement_debits": str(tally.statement_debits),
             "notes": tally.notes, "revision": tally.revision}
    ChangeLog.objects.create(owner=owner, action="bank_tally_saved", object_label=f"{account.name} · {month:%B %Y}",
                             details={"before": before, "after": after})
    record_submission(owner, token, digest, tally.pk)
    return tally


@transaction.atomic
def reverse_stock(movement, owner, *, reason, token):
    lock_workspace(owner)
    movement = StockMovement.objects.get(pk=movement.pk, product__owner=owner)
    digest = fingerprint("reverse_stock", {"id": movement.pk, "reason": reason})
    prior = prior_submission(owner, token, digest)
    if prior:
        return StockReversal.objects.get(pk=prior, owner=owner)
    if not reason.strip():
        raise ValidationError("A correction reason is required.")
    if StockReversal.objects.filter(movement=movement).exists():
        raise ValidationError("This movement was already reversed.")
    require_open_months(owner, movement.date, inventory=True)
    remaining = movement.product.movements.filter(reversal__isnull=True).exclude(pk=movement.pk).order_by("date", "pk")
    try:
        validate_stock_timeline(remaining)
    except ValueError as exc:
        raise ValidationError("Cannot reverse this receipt while later stock movements depend on it.") from exc
    reversal = StockReversal.objects.create(owner=owner, movement=movement, reason=reason)
    if movement.inventory_lot_id:
        # If a receipt is cancelled, its payment remains real. Reclassify the linked
        # payment from inventory asset cost to current operating expense.
        linked_costs = Entry.objects.filter(inventory_lot_id=movement.inventory_lot_id,
            owner=owner, voided_at__isnull=True, capitalized_inventory_cost=True)
        for entry in linked_costs:
            require_open_months(owner, entry.date)
            entry.capitalized_inventory_cost = False
            entry.revision += 1
            entry.save(update_fields=["capitalized_inventory_cost", "revision", "updated_at"])
            ChangeLog.objects.create(owner=owner, action="inventory_cost_reclassified",
                object_label=f"Transaction #{entry.pk}", details={"reason": reason, "inventory_lot": movement.inventory_lot_id})
    recompute_lot_depletions(movement.product)
    ChangeLog.objects.create(owner=owner, action="stock_reversed", object_label=f"Movement #{movement.pk}",
                             details={"reason": reason, "date": str(movement.date), "kind": movement.kind, "quantity": movement.quantity})
    record_submission(owner, token, digest, reversal.pk)
    return reversal


@transaction.atomic
def change_month(owner, month, *, close, reason, expected_state, token):
    lock_workspace(owner)
    start, end = month_bounds(month)
    digest = fingerprint("change_month", {"month": month, "close": close, "reason": reason, "state": expected_state})
    prior = prior_submission(owner, token, digest)
    if prior:
        return MonthReview.objects.get(pk=prior, owner=owner)
    review, _ = MonthReview.objects.get_or_create(owner=owner, month=start)
    if str(review.revision) != expected_state:
        raise ValidationError("This month changed since you opened the review. Refresh and review again.")
    if not reason.strip():
        raise ValidationError("A review/reopening reason is required.")
    if close:
        if end > timezone.localdate():
            raise ValidationError("Only a completed month can be closed.")
        if review.closed_at:
            raise ValidationError("This month is already closed.")
        data = report(owner, start, end)
        review.snapshot = {"totals": {k: str(v) for k, v in data["totals"].items()},
                           "bags_sold": data["sold_bags"], "thrift_sold": data["sold_thrift"],
                           "stock": {p.sku: product_stats(p, start, end)["stock_at_month_end"] for p in Product.objects.filter(owner=owner)}}
        review.closed_at = timezone.now()
    else:
        if not review.closed_at:
            raise ValidationError("This month is already open.")
        review.closed_at = None
    review.revision += 1
    review.save()
    ChangeLog.objects.create(owner=owner, action="month_closed" if close else "month_reopened", object_label=month,
                             details={"reason": reason, "snapshot": review.snapshot, "revision": review.revision})
    record_submission(owner, token, digest, review.pk)
    return review


def setup_defaults(owner):
    accounts = [("Bank 1", "bank"), ("Bank 2", "bank"), ("Cash", "cash"), ("Credit card", "card"),
                ("CRED wallet", "wallet"), ("Gift card", "wallet"), ("Paid by someone else", "other")]
    for name, kind in accounts:
        Account.objects.get_or_create(owner=owner, name=name, defaults={"kind": kind})
    for name in ("Manufacturing", "Packaging material", "Shipping & transit", "Warehouse", "Samples",
                 "Tech & subscriptions", "Staff salaries", "General", "Refund"):
        Category.objects.get_or_create(owner=owner, name=name)
