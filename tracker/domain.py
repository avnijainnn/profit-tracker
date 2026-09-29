"""Small framework-free rules, shared by reports, validation and unit tests."""
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")
INWARD_MOVEMENTS = frozenset({"received", "returned", "adjust_in"})


def month_bounds(value):
    """Strict YYYY-MM -> inclusive start, exclusive end."""
    if len(value) != 7 or value[4] != "-":
        raise ValueError("Use YYYY-MM")
    year, month = (int(part) for part in value.split("-"))
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def statement_summary(entries):
    """Entries expose kind/amount. Transfers are never revenue or spending."""
    totals = {"income": ZERO, "expense": ZERO, "withdrawal": ZERO, "transfer": ZERO}
    for entry in entries:
        if not getattr(entry, "voided_at", None):
            totals[entry.kind] += entry.amount
    totals["result"] = totals["income"] - totals["expense"]
    totals["after_withdrawals"] = totals["result"] - totals["withdrawal"]
    return totals


def stock_delta(kind, quantity):
    if kind not in INWARD_MOVEMENTS | {"sold", "damaged", "adjust_out"}:
        raise ValueError("Unknown stock movement")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise ValueError("Quantity must be a positive whole number")
    return quantity if kind in INWARD_MOVEMENTS else -quantity


def validate_stock_timeline(movements):
    """Caller supplies movements ordered by effective date, then entry order."""
    balance = 0
    for movement in movements:
        balance += stock_delta(movement.kind, movement.quantity)
        if balance < 0:
            raise ValueError("This would make stock negative. Record the earlier receipt/opening stock first.")
    return balance


def safe_csv_cell(value):
    """Prevent user-entered spreadsheet formulas from executing on CSV open."""
    value = str(value or "")
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value
