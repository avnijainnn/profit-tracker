"""Read-only summaries for the client's simple payment and stock screens."""
from decimal import Decimal

from django.db.models import Case, F, IntegerField, Q, Sum, When
from django.db.models.functions import TruncMonth

from .models import Account, Entry, StockMovement


ZERO = Decimal("0.00")


def amount_aggregates():
    return {
        **{kind: Sum("amount", filter=Q(kind=kind)) for kind in Entry.Kind.values},
        "cash_expense": Sum("amount", filter=Q(kind=Entry.Kind.EXPENSE) & ~Q(account__kind=Account.Kind.OTHER)),
    }


def money_totals(amounts):
    totals = {key: (amounts.get(key) or ZERO).quantize(Decimal("0.01"))
              for key in (*Entry.Kind.values, "cash_expense")}
    totals["result"] = totals["income"] - totals["expense"]
    totals["after_withdrawals"] = totals["result"] - totals["withdrawal"]
    totals["cash_profit"] = totals["income"] - totals["cash_expense"]
    return totals


def active_entries(owner, start, end):
    return Entry.objects.filter(owner=owner, date__gte=start, date__lt=end, voided_at__isnull=True)


def monthly_totals(owner, start, end):
    return money_totals(active_entries(owner, start, end).aggregate(**amount_aggregates()))


def yearly_totals(owner, year):
    from datetime import date
    amounts = active_entries(owner, date(year, 1, 1), date(year + 1, 1, 1)).order_by().annotate(
        period=TruncMonth("date")).values("period").annotate(**amount_aggregates())
    return {row["period"].month: money_totals(row) for row in amounts}


def payment_totals(owner, start, end):
    amounts = active_entries(owner, start, end).order_by().values("account_id").annotate(
        received=Sum("amount", filter=Q(kind=Entry.Kind.INCOME)),
        expenses=Sum("amount", filter=Q(kind=Entry.Kind.EXPENSE)))
    by_account = {row["account_id"]: row for row in amounts}
    rows = []
    totals = {"received": ZERO, "expenses": ZERO}
    for account in Account.objects.filter(owner=owner):
        amounts = by_account.get(account.pk, {})
        row = {"account": account, **{key: (amounts.get(key) or ZERO).quantize(Decimal("0.01"))
                                    for key in totals}}
        rows.append(row)
        for key in totals:
            totals[key] += row[key]
    return {"rows": rows, "totals": totals}


def stock_totals(owner, start, end):
    signed_units = Case(
        When(kind__in=["received", "returned", "adjust_in"], then=F("quantity")),
        default=-F("quantity"), output_field=IntegerField())
    amounts = StockMovement.objects.filter(product__owner=owner, reversal__isnull=True).order_by().values(
        "product_id").annotate(
        available=Sum(signed_units),
        stock_at_month_end=Sum(signed_units, filter=Q(date__lt=end)),
        month_sold=Sum("quantity", filter=Q(kind="sold", date__gte=start, date__lt=end)))
    return {row["product_id"]: {key: row[key] or 0 for key in ("available", "stock_at_month_end", "month_sold")}
            for row in amounts}


EMPTY_STOCK = {"available": 0, "stock_at_month_end": 0, "month_sold": 0}
