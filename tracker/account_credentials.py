"""Let an owner change login credentials without changing workspace ownership."""

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .models import ChangeLog


class LoginDetailsForm(forms.Form):
    email = forms.EmailField(label="Sign-in email", widget=forms.EmailInput(attrs={
        "class": "form-control", "autocomplete": "email"
    }))
    current_password = forms.CharField(widget=forms.PasswordInput(attrs={
        "class": "form-control", "autocomplete": "current-password"
    }))
    new_password1 = forms.CharField(required=False, label="New password (optional)",
                                    widget=forms.PasswordInput(attrs={
                                        "class": "form-control", "autocomplete": "new-password"
                                    }))
    new_password2 = forms.CharField(required=False, label="Confirm new password",
                                    widget=forms.PasswordInput(attrs={
                                        "class": "form-control", "autocomplete": "new-password"
                                    }))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        kwargs.setdefault("initial", {"email": user.email})
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().casefold()
        if get_user_model().objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("This email is already used by another account.")
        return email

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Current password is incorrect.")
        return password

    def clean(self):
        cleaned = super().clean()
        first = cleaned.get("new_password1")
        second = cleaned.get("new_password2")
        if first != second:
            self.add_error("new_password2", "New passwords do not match.")
        elif first:
            candidate = get_user_model()(username=self.user.username,
                                         email=cleaned.get("email") or self.user.email)
            try:
                validate_password(first, candidate)
            except ValidationError as exc:
                self.add_error("new_password1", exc)
        if not first and "email" in cleaned and cleaned["email"] == self.user.email.casefold():
            raise forms.ValidationError("Enter a new email or a new password.")
        return cleaned


@sensitive_post_parameters("current_password", "new_password1", "new_password2")
@login_required
@require_http_methods(["GET", "POST"])
def account_credentials(request):
    form = LoginDetailsForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [7319041203])
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            email = form.cleaned_data["email"]
            if not user.check_password(form.cleaned_data["current_password"]):
                form.add_error("current_password", "Current password is incorrect.")
            if get_user_model().objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                form.add_error("email", "This email is already used by another account.")
            if not form.errors:
                email_changed = user.email.casefold() != email
                password_changed = bool(form.cleaned_data["new_password1"])
                user.email = email
                if password_changed:
                    user.set_password(form.cleaned_data["new_password1"])
                user.save(update_fields=["email", "password"] if password_changed else ["email"])
                ChangeLog.objects.create(owner=user, action="login_details_changed",
                                         object_label="Account login", details={
                                             "email_changed": email_changed,
                                             "password_changed": password_changed,
                                         })
        if not form.errors:
            if password_changed:
                update_session_auth_hash(request, user)
            messages.success(request, "Login details updated. Your workspace data is unchanged.")
            return redirect("account_credentials")
    return render(request, "registration/account_credentials.html", {"form": form})
