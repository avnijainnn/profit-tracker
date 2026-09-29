from .services import chosen_month
from django.conf import settings


def review_month(request):
    """Keep the workspace navigation in the selected month, including settings/history."""
    return {**chosen_month(request), "demo_mode": settings.DEMO_MODE}
