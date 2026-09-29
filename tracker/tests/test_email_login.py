from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from tracker.models import Account
from tracker.services import setup_defaults


@override_settings(AXES_ENABLED=True, PASSWORD_RESET_ENABLED=False)
class EmailLoginTests(TestCase):
    def setUp(self):
        self.password = "Private-test-only!8392026"
        self.user = get_user_model().objects.create_user(
            "existing_owner", email="Owner@Example.test", password=self.password,
        )
        setup_defaults(self.user)

    def login(self, email="owner@example.test", password=None, **extra):
        return self.client.post(reverse("login"), {
            "username": email, "password": self.password if password is None else password,
            **extra,
        })

    def test_email_sign_in_opens_existing_workspace_without_second_step(self):
        accounts = list(Account.objects.filter(owner=self.user).values_list("pk", flat=True))
        response = self.login("  OWNER@EXAMPLE.TEST  ")
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard["Cache-Control"], "no-store, private")
        self.assertNotContains(dashboard, "/account/two_factor/")
        self.assertEqual(accounts, list(Account.objects.filter(owner=self.user).values_list("pk", flat=True)))

    def test_username_is_not_accepted_as_email(self):
        self.assertEqual(self.login(self.user.username).status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_password_and_unknown_email_have_same_generic_error(self):
        for email in ("owner@example.test", "missing@example.test"):
            with self.subTest(email=email):
                response = self.login(email, password="Wrong-password!123")
                self.assertContains(response, "Your email or password was not recognized.")
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_account_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.assertContains(self.login(), "Your email or password was not recognized.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ambiguous_legacy_email_fails_closed(self):
        get_user_model().objects.create_user(
            "duplicate_owner", email="OWNER@example.test", password=self.password,
        )
        self.assertContains(self.login(), "Your email or password was not recognized.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_failed_attempts_share_lockout_across_email_casing(self):
        for email in ("owner@example.test", "OWNER@example.test", "Owner@Example.test",
                      " owner@example.test ", "OWNER@EXAMPLE.TEST"):
            self.login(email, password="Wrong-password!123")
        self.assertEqual(self.login().status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_clears_email_failure_counter(self):
        from axes.models import AccessAttempt
        self.login(password="Wrong-password!123")
        self.assertTrue(AccessAttempt.objects.exists())
        self.assertRedirects(self.login(), reverse("dashboard"))
        self.assertFalse(AccessAttempt.objects.exists())

    def test_logout_requires_post_and_blocks_workspace_afterwards(self):
        self.login()
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
        self.assertRedirects(
            self.client.get(reverse("dashboard")), reverse("login") + "?next=/",
        )

    def test_login_honors_local_next_but_rejects_external_redirect(self):
        self.assertRedirects(self.login(next="/products/"), "/products/")
        self.client.logout()
        self.assertRedirects(self.login(next="https://untrusted.example/"), reverse("dashboard"))

    def test_login_post_requires_csrf_token(self):
        response = Client(enforce_csrf_checks=True).post(reverse("login"), {
            "username": self.user.email, "password": self.password,
        })
        self.assertEqual(response.status_code, 403)

    def test_login_page_has_only_email_and_password_credentials(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'type="email"')
        self.assertContains(response, 'type="password"')
        self.assertNotContains(response, "Forgot your password?")
        for path in ("/account/two_factor/", "/account/two_factor/setup/"):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertRedirects(self.client.get("/account/login/?next=/products/"), "/login/?next=/products/")

    def test_admin_email_login_requires_staff_permission(self):
        response = self.client.post(reverse("admin:login"), {
            "username": self.user.email, "password": self.password, "next": "/admin/",
        })
        self.assertContains(response, "Your email or password was not recognized.")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.user.is_staff = True
        self.user.save()
        response = self.client.post(reverse("admin:login"), {
            "username": self.user.email, "password": self.password, "next": "/admin/",
        })
        self.assertRedirects(response, "/admin/")
