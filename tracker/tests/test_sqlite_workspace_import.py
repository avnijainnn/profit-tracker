"""Exercise a complete SQLite-to-PostgreSQL transfer on CI's PostgreSQL service."""

import hashlib
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.test import TransactionTestCase
from PIL import Image

from tracker.models import Account, Category, Entry, Product, StoredUpload


@skipUnless(connection.vendor == "postgresql", "Requires an empty PostgreSQL test database")
class SQLiteWorkspaceImportTests(TransactionTestCase):
    def test_transfer_preserves_records_photo_and_source_then_refuses_second_import(self):
        with TemporaryDirectory(prefix="profit-import-test-") as temporary:
            root = Path(temporary)
            source_db = root / "source.sqlite3"
            media_root = root / "media"
            alias = "transfer_source"
            source_config = settings.DATABASES["default"].copy()
            source_config.update({
                "ENGINE": "django.db.backends.sqlite3", "NAME": str(source_db),
                "OPTIONS": {"timeout": 30}, "HOST": "", "PORT": "", "USER": "", "PASSWORD": "",
                "CONN_MAX_AGE": 0, "CONN_HEALTH_CHECKS": False,
            })
            connections.databases[alias] = source_config
            try:
                call_command("migrate", database=alias, interactive=False, verbosity=0)
                User = get_user_model()
                owner = User.objects.db_manager(alias).create_user(
                    "owner", email="old@example.test", password="Old-private-password-8392!",
                )
                account = Account.objects.using(alias).create(owner=owner, name="Client bank", kind="bank")
                category = Category.objects.using(alias).create(owner=owner, name="Materials")
                photo_name = f"products/{owner.pk}/client.jpg"
                image = BytesIO()
                Image.new("RGB", (2, 2), "blue").save(image, format="JPEG")
                photo_data = image.getvalue()
                photo_path = media_root / photo_name
                photo_path.parent.mkdir(parents=True)
                photo_path.write_bytes(photo_data)
                product = Product.objects.using(alias).create(
                    owner=owner, sku="CLIENT-BAG", name="Client bag", photo=photo_name,
                )
                entry = Entry.objects.using(alias).create(
                    owner=owner, kind="expense", date=date(2026, 9, 29),
                    amount=Decimal("125.00"), account=account, category=category,
                    product=product, notes="Actual client expense",
                )
                connections[alias].close()
                before = hashlib.sha256(source_db.read_bytes()).hexdigest()
                output = StringIO()
                call_command("import_sqlite_workspace", source_db=str(source_db),
                             media_root=str(media_root), apply=True, stdout=output)
                self.assertIn("transferred and verified", output.getvalue())
                self.assertEqual(hashlib.sha256(source_db.read_bytes()).hexdigest(), before)
                imported_owner = User.objects.get(pk=owner.pk)
                self.assertEqual(imported_owner.email, "old@example.test")
                self.assertTrue(imported_owner.check_password("Old-private-password-8392!"))
                self.assertEqual(Entry.objects.get(pk=entry.pk).notes, "Actual client expense")
                self.assertEqual(Product.objects.get(pk=product.pk).photo.name, photo_name)
                self.assertEqual(bytes(StoredUpload.objects.get(path=photo_name).data), photo_data)
                with self.assertRaisesMessage(CommandError, "destination already contains"):
                    call_command("import_sqlite_workspace", source_db=str(source_db),
                                 media_root=str(media_root), apply=True, stdout=StringIO())
            finally:
                connections[alias].close()
                connections.databases.pop(alias, None)
