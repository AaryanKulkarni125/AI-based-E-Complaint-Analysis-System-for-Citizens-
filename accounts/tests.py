from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import LoginAudit, User


class LoginLogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_defaults", force=True, verbosity=0)

    def login(self, username, password, **extra):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": password}, **extra)

    def test_each_role_can_log_in_and_sees_own_dashboard(self):
        cases = [
            ("citizen1", "Citizen@2026", "Citizen dashboard"),
            ("officer1", "Officer@2026", "Officer dashboard"),
            ("sysadmin", "SysAdmin@2026", "System administrator dashboard"),
        ]
        for username, password, heading in cases:
            with self.subTest(username=username):
                response = self.login(username, password)
                self.assertRedirects(response, reverse("accounts:dashboard"))
                self.assertContains(self.client.get(reverse("accounts:dashboard")), heading)
                self.client.post(reverse("accounts:logout"))

    def test_wrong_password_rejected_and_audited(self):
        response = self.login("citizen1", "nope12345")
        self.assertContains(response, "Incorrect username or password.")
        self.assertFalse("_auth_user_id" in self.client.session)
        self.assertEqual(LoginAudit.objects.filter(outcome="failed", username="citizen1").count(), 1)

    def test_unknown_user_gets_same_message(self):
        response = self.login("ghost", "whatever123")
        self.assertContains(response, "Incorrect username or password.")

    def test_logout_requires_post_and_ends_session(self):
        self.login("citizen1", "Citizen@2026")
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)

    def test_lockout_after_five_failures_blocks_even_correct_password(self):
        for _ in range(5):
            self.login("citizen1", "badpass123")
        response = self.login("citizen1", "Citizen@2026")
        self.assertContains(response, "locked")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(LoginAudit.objects.filter(outcome="locked").exists())

    def test_four_failures_do_not_lock(self):
        for _ in range(4):
            self.login("citizen1", "badpass123")
        self.assertRedirects(self.login("citizen1", "Citizen@2026"), reverse("accounts:dashboard"))

    def test_open_redirect_is_blocked(self):
        response = self.client.post(
            reverse("accounts:login") + "?next=https://evil.example/",
            {"username": "citizen1", "password": "Citizen@2026"},
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))

    def test_deactivated_account_cannot_log_in(self):
        User.objects.filter(username="citizen1").update(is_active=False)
        self.assertContains(self.login("citizen1", "Citizen@2026"), "Incorrect username or password.")

    def test_seed_is_idempotent(self):
        call_command("seed_defaults", force=True, verbosity=0)
        self.assertEqual(User.objects.count(), 3)


class RegistrationTests(TestCase):
    def payload(self, **overrides):
        data = {
            "username": "newuser",
            "first_name": "New",
            "last_name": "User",
            "email": "newuser@example.com",
            "password1": "Sup3rSecret99",
            "password2": "Sup3rSecret99",
        }
        data.update(overrides)
        return data

    def register(self, role, **overrides):
        return self.client.post(reverse("accounts:register", args=[role]), self.payload(**overrides))

    def test_citizen_registers_then_logs_in(self):
        self.assertRedirects(self.register("citizen"), reverse("accounts:login"))
        user = User.objects.get(username="newuser")
        self.assertEqual(user.role, User.Role.CITIZEN)
        self.assertNotEqual(user.password, "Sup3rSecret99")  # hashed
        self.assertTrue(self.client.login(username="newuser", password="Sup3rSecret99"))

    def test_officer_registers_with_code_and_gets_profile(self):
        response = self.register("officer", registration_code="OFFICER-DEV-2026", department="Roads")
        self.assertRedirects(response, reverse("accounts:login"))
        user = User.objects.get(username="newuser")
        self.assertEqual(user.role, User.Role.OFFICER)
        self.assertEqual(user.officer_profile.department, "Roads")
        self.assertEqual(user.officer_profile.availability_status, "active")

    def test_admin_registers_with_code_but_is_not_django_staff(self):
        self.register("admin", registration_code="SYSADMIN-DEV-2026")
        user = User.objects.get(username="newuser")
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_privileged_roles_reject_wrong_or_missing_code(self):
        for role, department in (("officer", "Roads"), ("admin", "")):
            extra = {"department": department} if department else {}
            self.assertContains(self.register(role, registration_code="guess", **extra), "Invalid registration code")
            self.assertEqual(self.register(role, **extra).status_code, 200)  # missing code
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_officer_code_does_not_work_for_admin(self):
        self.register("admin", registration_code="OFFICER-DEV-2026")
        self.assertFalse(User.objects.exists())

    def test_duplicate_username_and_email_rejected_case_insensitively(self):
        self.register("citizen")
        self.assertContains(self.register("citizen", email="other@example.com", username="NewUser"), "already exists")
        self.assertContains(self.register("citizen", username="other", email="NEWUSER@example.com"), "already exists")
        self.assertEqual(User.objects.count(), 1)

    def test_password_policy(self):
        weak = {
            "short": "ab1",
            "numeric only": "98765432101",
            "letters only": "OnlyLettersHere",
            "too common": "password123",
            "similar to username": "newuser123",
        }
        for label, pw in weak.items():
            with self.subTest(label):
                response = self.register("citizen", password1=pw, password2=pw)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(User.objects.exists())

    def test_password_mismatch(self):
        self.assertEqual(self.register("citizen", password2="Different123").status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_unknown_role_404_and_logged_in_users_redirected(self):
        self.assertEqual(self.client.get(reverse("accounts:register", args=["hacker"])).status_code, 404)
        User.objects.create_user("x", "x@example.com", "Passw0rd!xyz")
        self.client.login(username="x", password="Passw0rd!xyz")
        self.assertRedirects(self.client.get(reverse("accounts:register_choice")), reverse("accounts:dashboard"))

    def test_registration_code_guessing_is_throttled(self):
        from django.core.cache import cache

        cache.clear()
        for _ in range(10):
            self.register("admin", registration_code="wrong")
        # Even the right code is refused once the limit is hit.
        self.register("admin", registration_code="SYSADMIN-DEV-2026")
        self.assertFalse(User.objects.exists())
        cache.clear()


class ProfileAndSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testcitizen",
            email="citizen@example.com",
            password="StrongPassword123",
            role=User.Role.CITIZEN,
            first_name="Test",
            last_name="Citizen",
            phone="9876543210",
        )
        self.client.force_login(self.user)

    def test_view_profile(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "testcitizen")
        self.assertContains(response, "citizen@example.com")

    def test_edit_profile_success(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Updated",
                "last_name": "Name",
                "email": "updated@example.com",
                "phone": "9998887776",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertEqual(self.user.phone, "9998887776")

    def test_edit_profile_duplicate_email_rejected(self):
        User.objects.create_user(
            username="otheruser",
            email="existing@example.com",
            password="StrongPassword123",
        )
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "first_name": "Test",
                "last_name": "Citizen",
                "email": "existing@example.com",
                "phone": "9876543210",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already in use")

    def test_change_password_success(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "current_password": "StrongPassword123",
                "new_password1": "NewPassw0rd99!",
                "new_password2": "NewPassw0rd99!",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPassw0rd99!"))

    def test_change_password_wrong_current_rejected(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "current_password": "WrongPassword99",
                "new_password1": "NewPassw0rd99!",
                "new_password2": "NewPassw0rd99!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Current password is incorrect.")

    def test_password_reset_request(self):
        self.client.logout()
        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "citizen@example.com"},
        )
        self.assertRedirects(response, reverse("accounts:login"))


class OTPAuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="otpuser",
            email="otpuser@example.com",
            password="StrongPassw0rd123",
            role=User.Role.CITIZEN,
            phone="9123456789",
        )

    def test_request_otp_generates_token(self):
        from accounts.models import OTPToken

        response = self.client.post(
            reverse("accounts:otp_request"),
            {"identifier": "otpuser@example.com"},
        )
        self.assertRedirects(response, reverse("accounts:otp_verify"))
        token = OTPToken.objects.filter(user=self.user).first()
        self.assertIsNotNone(token)
        self.assertEqual(len(token.code), 6)
        self.assertTrue(token.is_valid())

    def test_verify_valid_otp_logs_in(self):
        from accounts.models import OTPToken

        self.client.post(
            reverse("accounts:otp_request"),
            {"identifier": "otpuser"},
        )
        token = OTPToken.objects.get(user=self.user)
        response = self.client.post(
            reverse("accounts:otp_verify"),
            {"otp_code": token.code},
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        token.refresh_from_db()
        self.assertTrue(token.is_used)

    def test_invalid_otp_rejected(self):
        from accounts.models import LoginAudit

        self.client.post(
            reverse("accounts:otp_request"),
            {"identifier": "otpuser"},
        )
        response = self.client.post(
            reverse("accounts:otp_verify"),
            {"otp_code": "000000"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid or expired")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(LoginAudit.objects.filter(username="otpuser", outcome="failed").exists())
