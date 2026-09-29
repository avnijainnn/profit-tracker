from django.conf import settings
from django.shortcuts import redirect
from django.urls import resolve, Resolver404
from django_otp import devices_for_user


def no_client_ip(request):
    """Lock by username; don't trust arbitrary forwarded IP headers or retain IPs."""
    return None


class RequireVerifiedSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.REQUIRE_2FA and request.user.is_authenticated:
            try:
                match = resolve(request.path_info)
            except Resolver404:
                match = None
            recovery_names = {"logout", "password_reset", "password_reset_done", "password_reset_confirm", "password_reset_complete", "health"}
            if match and match.namespace != "two_factor" and match.url_name not in recovery_names and not request.user.is_verified():
                enrolled = any(devices_for_user(request.user, confirmed=True))
                return redirect("two_factor:login" if enrolled else "two_factor:setup")
        response = self.get_response(request)
        # Financial pages and CSV exports should not remain in shared/browser caches.
        if request.user.is_authenticated:
            response["Cache-Control"] = "no-store, private"
        return response
