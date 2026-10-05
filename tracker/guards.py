"""Transactional guards. Call only inside atomic blocks, after workspace locking."""
import hashlib
import json
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import F
from .models import MonthReview, Submission


def lock_workspace(owner):
    # All money/stock/close operations acquire this lock first, avoiding lock-order races.
    users = get_user_model().objects
    if connection.vendor == "sqlite":
        # SQLite has no SELECT FOR UPDATE. Acquire its write lock before reading
        # money/stock state so concurrent submissions cannot both pass validation.
        if not users.filter(pk=owner.pk).update(last_login=F("last_login")):
            raise ValidationError("Workspace owner no longer exists.")
    else:
        users.select_for_update().get(pk=owner.pk)


def fingerprint(operation, payload):
    raw = json.dumps([operation, payload], sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def prior_submission(owner, token, digest):
    receipt = Submission.objects.filter(owner=owner, token=token).first()
    if receipt and receipt.fingerprint != digest:
        raise ValidationError("This form was already used with different values. Open a fresh form.")
    return receipt.object_id if receipt else None


def record_submission(owner, token, digest, object_id):
    Submission.objects.create(owner=owner, token=token, fingerprint=digest, object_id=object_id)


def require_open_months(owner, *dates, inventory=False):
    months = [value.replace(day=1) for value in dates]
    closed = MonthReview.objects.filter(owner=owner, closed_at__isnull=False)
    if inventory:
        # Backdating stock changes the ending inventory of every later month.
        closed = closed.filter(month__gte=min(months))
    else:
        closed = closed.filter(month__in=months)
    blocked = closed.order_by("month").first()
    if blocked:
        raise ValidationError(f"{blocked.month:%B %Y} is closed. Reopen affected months before making this change.")
