def no_client_ip(request):
    """Lock by account email without retaining or trusting client IP addresses."""
    return None


def login_identifier(request, credentials=None):
    """Use one lockout bucket for all casing/spacing variants of an email."""
    # Successful-login signals supply the internal username; the submitted
    # email keeps successful and failed attempts in the same lockout bucket.
    value = request.POST.get("username") if request is not None else None
    if value is None:
        value = (credentials or {}).get("username", "")
    return (value or "").strip().casefold()


class AuthenticatedNoCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            response["Cache-Control"] = "no-store, private"
        return response
