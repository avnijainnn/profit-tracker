from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from tracker.models import Account, ChangeLog, Entry, Product


TOKEN = "one-time-test-token-with-at-least-32-characters-8392"
PASSWORD = "Private-owner-password-8392!"


@override_settings(INITIAL_OWNER_SETUP_TOKEN=TOKEN, DEMO_MODE=False)
class OwnerSetupTests(TestCase):
    def test_private_link_creates_only_one_real_workspace(self):
        with patch.dict("os.environ", {"DEMO_SEED_DATA": "false", "INITIAL_OWNER_PASSWORD": ""}):
            output = StringIO()
            call_command("bootstrap_workspace", stdout=output)
        self.assertIn("one-time owner setup", output.getvalue())
        self.assertFalse(get_user_model().objects.exists())

        url = reverse("owner_setup")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(url + "?token=wrong").status_code, 404)
        response = self.client.get(url + "?token=" + TOKEN)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], url)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.client.get(url).status_code, 200)

        form = {"email": "CLIENT@EXAMPLE.TEST", "password1": PASSWORD, "password2": PASSWORD}
        weak = self.client.post(url, {**form, "password1": "weak", "password2": "weak"})
        self.assertEqual(weak.status_code, 200)
        self.assertFalse(get_user_model().objects.exists())

        response = self.client.post(url, form)
        self.assertRedirects(response, reverse("dashboard"))
        user = get_user_model().objects.get()
        self.assertEqual(user.email, "client@example.test")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(Account.objects.filter(owner=user).exists())
        self.assertFalse(Entry.objects.exists())
        self.assertFalse(Product.objects.exists())
        self.assertEqual(ChangeLog.objects.filter(owner=user, action="workspace_initialized").count(), 1)
        self.assertEqual(self.client.get(url + "?token=" + TOKEN).status_code, 404)
        self.assertEqual(self.client.post(url, form).status_code, 404)
        self.assertEqual(get_user_model().objects.count(), 1)

        self.client.logout()
        self.assertRedirects(self.client.post(reverse("login"), {
            "username": "client@example.test", "password": PASSWORD,
        }), reverse("dashboard"))

    @override_settings(INITIAL_OWNER_SETUP_TOKEN="")
    def test_setup_disabled_without_private_token(self):
        self.assertEqual(self.client.get(reverse("owner_setup")).status_code, 404)
