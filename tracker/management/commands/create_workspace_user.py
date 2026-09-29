from getpass import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from tracker.services import setup_defaults


class Command(BaseCommand):
    help = "Interactively create an ordinary user with their own isolated workspace."
    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(username=options["username"]).exists():
            raise CommandError("Username already exists. No account changed.")
        if User.objects.filter(email__iexact=options["email"]).exists():
            raise CommandError("Use a unique recovery email for each account.")
        try:
            validate_email(options["email"])
            user = User(username=options["username"], email=options["email"], is_staff=False, is_superuser=False)
            user.full_clean(exclude=["password"])
            password = getpass("New password (not displayed): ")
            if password != getpass("Repeat password: "):
                raise CommandError("Passwords do not match.")
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        user.set_password(password)
        user.save()
        setup_defaults(user)
        self.stdout.write(self.style.SUCCESS("Ordinary workspace user created. Enroll 2FA at first production login and save backup codes offline."))
