from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView
from tracker.authentication import EmailAuthenticationForm, EmailAdminAuthenticationForm
from tracker.auth_views import ThrottledPasswordResetView, require_password_reset_enabled
from tracker.owner_setup import owner_setup
from tracker.account_credentials import account_credentials

admin.site.login_form = EmailAdminAuthenticationForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("setup/", owner_setup, name="owner_setup"),
    path("account/details/", account_credentials, name="account_credentials"),
    path("login/", auth_views.LoginView.as_view(authentication_form=EmailAuthenticationForm), name="login"),
    path("account/login/", RedirectView.as_view(pattern_name="login", query_string=True, permanent=False)),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password-reset/", require_password_reset_enabled(ThrottledPasswordResetView.as_view()), name="password_reset"),
    path("password-reset/sent/", require_password_reset_enabled(auth_views.PasswordResetDoneView.as_view()), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", require_password_reset_enabled(auth_views.PasswordResetConfirmView.as_view()), name="password_reset_confirm"),
    path("password-reset/complete/", require_password_reset_enabled(auth_views.PasswordResetCompleteView.as_view()), name="password_reset_complete"),
    path("", include("tracker.urls")),
]
