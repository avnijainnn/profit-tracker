from datetime import timedelta
from functools import wraps
from django.contrib.auth.views import PasswordResetView
from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import RecoveryThrottle


def require_password_reset_enabled(view):
    @wraps(view)
    def guarded_view(request, *args, **kwargs):
        if not settings.PASSWORD_RESET_ENABLED:
            raise Http404
        return view(request, *args, **kwargs)
    return guarded_view


class ThrottledPasswordResetView(PasswordResetView):
    def form_valid(self, form):
        # No raw email is stored in the throttle table. All responses are generic.
        key = salted_hmac("profit-reset", form.cleaned_data["email"].strip().casefold(), algorithm="sha256").hexdigest()
        now = timezone.now()
        with transaction.atomic():
            RecoveryThrottle.objects.get_or_create(key=key, defaults={"window_started": now})
            row = RecoveryThrottle.objects.select_for_update().get(key=key)
            if row.window_started <= now - timedelta(hours=1):
                row.window_started, row.count = now, 0
            allowed = row.count < 3
            if allowed:
                row.count += 1
                row.save(update_fields=["count", "window_started"])
        if allowed:
            return super().form_valid(form)
        return HttpResponseRedirect(self.get_success_url())
