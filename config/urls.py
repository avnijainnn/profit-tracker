from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView
from two_factor.urls import urlpatterns as two_factor_urls
from two_factor.admin import AdminSiteOTPRequired
from tracker.auth_views import ThrottledPasswordResetView

admin.site.__class__ = AdminSiteOTPRequired

urlpatterns = [
    path("", include(two_factor_urls)),
    path("admin/", admin.site.urls),
    path("login/", RedirectView.as_view(pattern_name="two_factor:login", permanent=False), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password-reset/", ThrottledPasswordResetView.as_view(), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("", include("tracker.urls")),
]
