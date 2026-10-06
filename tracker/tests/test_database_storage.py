from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from tracker.models import Product, StoredUpload
from tracker.storage import DatabaseStorage


@override_settings(STORAGES={
    "default": {"BACKEND": "tracker.storage.DatabaseStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class DatabaseStorageTests(TestCase):
    def test_missing_legacy_photo_shows_placeholder_without_changing_product(self):
        user = get_user_model().objects.create_user(
            username="owner", email="owner@example.test", password="Test-only-private-password-123"
        )
        product = Product.objects.create(
            owner=user, sku="BAG-1", name="Bag", photo="products/old-missing.jpg"
        )
        self.client.force_login(user)
        photo_url = reverse("product_photo", args=[product.pk])

        for page_url in [reverse("products"), reverse("product_detail", args=[product.pk]),
                         reverse("product_edit", args=[product.pk])]:
            response = self.client.get(page_url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, photo_url)
        self.assertEqual(self.client.get(photo_url).status_code, 404)
        product.refresh_from_db()
        self.assertEqual(product.photo.name, "products/old-missing.jpg")

    def test_product_photo_survives_new_storage_instance_and_stays_private(self):
        user = get_user_model().objects.create_user(
            username="owner", email="owner@example.test", password="Test-only-private-password-123"
        )
        product = Product.objects.create(owner=user, sku="BAG-1", name="Bag")
        image = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(image, format="JPEG")
        payload = image.getvalue()
        product.photo.save("bag.jpg", ContentFile(payload), save=True)
        name = product.photo.name

        self.assertIsInstance(product.photo.storage, DatabaseStorage)
        self.assertEqual(StoredUpload.objects.count(), 1)
        self.assertEqual(DatabaseStorage().open(name).read(), payload)

        url = reverse("product_photo", args=[product.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(user)
        edit_response = self.client.get(reverse("product_edit", args=[product.pk]))
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, "Remove current photo")
        self.assertContains(edit_response, url)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), payload)
        self.assertTrue(response.closed)

        product.photo.delete(save=True)
        self.assertFalse(DatabaseStorage().exists(name))
        self.assertEqual(self.client.get(url).status_code, 404)
