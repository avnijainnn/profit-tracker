"""Private, one-time account setup for an empty single-owner deployment."""

import hashlib
import os
import secrets

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .models import ChangeLog
from .services import setup_defaults


SESSION_KEY = "owner_setup_token_digest"


class OwnerSetupForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}))
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={
        "class": "form-control", "autocomplete": "new-password"
    }))
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={
        "class": "form-control", "autocomplete": "new-password"
    }))

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password1")
        confirmation = cleaned.get("password2")
        if password and confirmation and password != confirmation:
            self.add_error("password2", "Passwords do not match.")
        elif password and cleaned.get("email"):
            user = get_user_model()(
                username=os.environ.get("INITIAL_OWNER_USERNAME", "owner").strip() or "owner",
                email=cleaned["email"].strip().casefold(),
            )
            try:
                validate_password(password, user)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


@sensitive_post_parameters("password1", "password2")
@never_cache
@require_http_methods(["GET", "POST"])
def owner_setup(request):
    token = settings.INITIAL_OWNER_SETUP_TOKEN
    User = get_user_model()
    if not token or len(token) < 32 or User.objects.exists():
        raise Http404

    digest = hashlib.sha256(token.encode()).hexdigest()
    supplied = request.GET.get("token", "") if request.method == "GET" else ""
    if supplied:
        if not secrets.compare_digest(supplied, token):
            raise Http404
        request.session.cycle_key()
        request.session[SESSION_KEY] = digest
        response = redirect("owner_setup")
        response["Referrer-Policy"] = "no-referrer"
        return response
    if not secrets.compare_digest(request.session.get(SESSION_KEY, ""), digest):
        raise Http404

    form = OwnerSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [7319041202])
            if User.objects.exists():
                raise Http404
            user = User(
                username=os.environ.get("INITIAL_OWNER_USERNAME", "owner").strip() or "owner",
                email=form.cleaned_data["email"].strip().casefold(),
                is_staff=False,
                is_superuser=False,
            )
            user.set_password(form.cleaned_data["password1"])
            user.full_clean()
            user.save()
            setup_defaults(user)
            ChangeLog.objects.create(owner=user, action="workspace_initialized",
                                     object_label="Initial workspace", details={"fictional_data": False})
        request.session.pop(SESSION_KEY, None)
        login(request, user, backend="tracker.authentication.EmailBackend")
        return redirect("dashboard")

    return render(request, "registration/owner_setup.html", {"form": form})
