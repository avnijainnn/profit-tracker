"""Exercise a complete SQLite-to-PostgreSQL transfer on CI's PostgreSQL service."""

import hashlib
import os
import subprocess
import sys
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase
from PIL import Image

from tracker.models import Entry, Product, StoredUpload


@skipUnless(connection.vendor == "postgresql", "Requires an empty PostgreSQL test database")
class SQLiteWorkspaceImportTests(TransactionTestCase):
    def test_transfer_preserves_records_photo_and_source_then_refuses_second_import(self):
        with TemporaryDirectory(prefix="profit-import-test-") as temporary:
            root = Path(temporary)
            source_db = root / "source.sqlite3"
            media_root = root / "media"
            photo_name = "products/1/client.jpg"
            image = BytesIO()
            Image.new("RGB", (2, 2), "blue").save(image, format="JPEG")
            photo_data = image.getvalue()
            photo_path = media_root / photo_name
            photo_path.parent.mkdir(parents=True)
            photo_path.write_bytes(photo_data)

            source_environment = os.environ.copy()
            source_environment.update({
                "DJANGO_SETTINGS_MODULE": "config.import_source_settings",
                "DJANGO_DEBUG": "true", "APP_ENV": "",
                "IMPORT_SOURCE_ONLY": "true", "IMPORT_BUILD_TEST_SOURCE": "true",
                "IMPORT_SOURCE_DB": str(source_db),
            })
            subprocess.run(
                [sys.executable, str(settings.BASE_DIR / "manage.py"), "migrate", "--noinput",
                 "--verbosity=0", "--settings=config.import_source_settings"],
                cwd=settings.BASE_DIR, env=source_environment, capture_output=True,
                text=True, check=True,
            )
            source_code = """
from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from tracker.models import Account, Category, Entry, Product
owner = get_user_model().objects.create_user('owner', email='old@example.test', password='Old-private-password-8392!')
account = Account.objects.create(owner=owner, name='Client bank', kind='bank')
category = Category.objects.create(owner=owner, name='Materials')
product = Product.objects.create(owner=owner, sku='CLIENT-BAG', name='Client bag', photo='products/1/client.jpg')
Entry.objects.create(owner=owner, kind='expense', date=date(2026, 9, 29), amount=Decimal('125.00'), account=account, category=category, product=product, notes='Actual client expense')
"""
            subprocess.run(
                [sys.executable, str(settings.BASE_DIR / "manage.py"), "shell", "-c", source_code,
                 "--settings=config.import_source_settings"],
                cwd=settings.BASE_DIR, env=source_environment, capture_output=True,
                text=True, check=True,
            )
            before = hashlib.sha256(source_db.read_bytes()).hexdigest()
            output = StringIO()
            call_command("import_sqlite_workspace", source_db=str(source_db),
                         media_root=str(media_root), apply=True, stdout=output)
            self.assertIn("transferred and verified", output.getvalue())
            self.assertEqual(hashlib.sha256(source_db.read_bytes()).hexdigest(), before)
            imported_owner = get_user_model().objects.get(pk=1)
            self.assertEqual(imported_owner.email, "old@example.test")
            self.assertTrue(imported_owner.check_password("Old-private-password-8392!"))
            self.assertEqual(Entry.objects.get(pk=1).notes, "Actual client expense")
            self.assertEqual(Product.objects.get(pk=1).photo.name, photo_name)
            self.assertEqual(bytes(StoredUpload.objects.get(path=photo_name).data), photo_data)
            with self.assertRaisesMessage(CommandError, "destination already contains"):
                call_command("import_sqlite_workspace", source_db=str(source_db),
                             media_root=str(media_root), apply=True, stdout=StringIO())
