"""Email/password authentication for existing Django user accounts."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = (username or "").strip().casefold()
        if not email or password is None:
            return None
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=email)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            # Avoid fast responses for unknown or ambiguous email addresses.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


class EmailAuthenticationForm(AuthenticationForm):
    # Keep Django's field name for compatibility with LoginView and Axes.
    username = forms.EmailField(
        label="Email", max_length=254,
        widget=forms.EmailInput(attrs={
            "class": "form-control", "autocomplete": "username",
            "autofocus": True, "autocapitalize": "none",
        }),
    )
    error_messages = {
        "invalid_login": "Your email or password was not recognized.",
        "inactive": "Your email or password was not recognized.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].max_length = 254
        self.fields["username"].widget.attrs["maxlength"] = 254
        self.fields["password"].widget.attrs["class"] = "form-control"

    def clean_username(self):
        return self.cleaned_data["username"].strip().casefold()


class EmailAdminAuthenticationForm(EmailAuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError(self.error_messages["invalid_login"], code="invalid_login")
