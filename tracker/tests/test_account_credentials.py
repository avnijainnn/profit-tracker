from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from tracker.models import Account, ChangeLog, Product
from tracker.services import setup_defaults


OLD_PASSWORD = "Old-private-password-8392!"
NEW_PASSWORD = "New-private-password-8392!"


class AccountCredentialsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "owner", email="old@example.test", password=OLD_PASSWORD,
        )
        setup_defaults(self.user)
        self.product = Product.objects.create(owner=self.user, sku="BAG-1", name="Bag")
        self.account_ids = list(Account.objects.filter(owner=self.user).values_list("pk", flat=True))
        self.url = reverse("account_credentials")

    def change(self, **changes):
        data = {
            "username": "newowner",
            "email": "new@example.test",
            "current_password": OLD_PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        }
        data.update(changes)
        return self.client.post(self.url, data)

    def test_owner_changes_login_without_moving_data(self):
        self.client.force_login(self.user, backend="tracker.authentication.EmailBackend")
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertRedirects(self.change(), self.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newowner")
        self.assertEqual(self.user.email, "new@example.test")
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertEqual(self.product.owner_id, self.user.pk)
        self.assertEqual(self.account_ids, list(Account.objects.filter(owner=self.user).values_list("pk", flat=True)))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertContains(self.client.get(reverse("dashboard")), "newowner")
        self.assertEqual(ChangeLog.objects.filter(owner=self.user, action="login_details_changed").count(), 1)

        self.client.logout()
        self.assertEqual(self.client.post(reverse("login"), {
            "username": "old@example.test", "password": OLD_PASSWORD,
        }).status_code, 200)
        self.assertRedirects(self.client.post(reverse("login"), {
            "username": "new@example.test", "password": NEW_PASSWORD,
        }), reverse("dashboard"))

    def test_wrong_current_password_and_existing_email_are_rejected(self):
        other = get_user_model().objects.create_user(
            "other", email="taken@example.test", password="Other-private-password-8392!",
        )
        self.client.force_login(self.user, backend="tracker.authentication.EmailBackend")
        response = self.change(current_password="wrong")
        self.assertContains(response, "Current password is incorrect.")
        response = self.change(email="TAKEN@EXAMPLE.TEST")
        self.assertContains(response, "This email is already used by another account.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@example.test")
        self.assertEqual(self.user.username, "owner")
        self.assertTrue(self.user.check_password(OLD_PASSWORD))
        self.assertEqual(other.email, "taken@example.test")

    def test_username_only_change_keeps_email_password_and_records(self):
        self.client.force_login(self.user, backend="tracker.authentication.EmailBackend")
        self.assertRedirects(self.change(
            email="old@example.test", new_password1="", new_password2="",
        ), self.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newowner")
        self.assertEqual(self.user.email, "old@example.test")
        self.assertTrue(self.user.check_password(OLD_PASSWORD))
        self.assertEqual(self.product.owner_id, self.user.pk)
        self.assertEqual(self.account_ids, list(Account.objects.filter(owner=self.user).values_list("pk", flat=True)))
        self.assertContains(self.client.get(reverse("dashboard")), "newowner")
        self.assertEqual(ChangeLog.objects.get(owner=self.user, action="login_details_changed").details, {
            "username_changed": True, "email_changed": False, "password_changed": False,
        })

    def test_duplicate_and_invalid_usernames_are_rejected(self):
        get_user_model().objects.create_user("Other", email="other@example.test", password=NEW_PASSWORD)
        self.client.force_login(self.user, backend="tracker.authentication.EmailBackend")
        self.assertContains(self.change(username="oThEr"), "This username is already used by another account.")
        self.assertContains(self.change(username="name with spaces"), "Enter a valid username.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "owner")
        self.assertEqual(self.user.email, "old@example.test")
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_unchanged_details_require_a_change(self):
        self.client.force_login(self.user, backend="tracker.authentication.EmailBackend")
        self.assertContains(self.change(
            username="owner", email="old@example.test", new_password1="", new_password2="",
        ), "Enter a new username, email, or password.")

    def test_change_requires_login_and_csrf(self):
        self.assertRedirects(self.client.get(self.url), reverse("login") + "?next=" + self.url)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user, backend="tracker.authentication.EmailBackend")
        self.assertEqual(csrf_client.post(self.url, {
            "email": "new@example.test", "current_password": OLD_PASSWORD,
        }).status_code, 403)
