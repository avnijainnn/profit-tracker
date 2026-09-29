from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()

@register.filter
def money(value):
    try:
        value = Decimal(value or 0)
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    sign = "−" if value < 0 else ""
    whole, fraction = f"{abs(value):.2f}".split(".")
    tail = whole[-3:]
    head = whole[:-3]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    grouped = ",".join([*groups, tail])
    return f"{sign}₹{grouped}.{fraction}"
