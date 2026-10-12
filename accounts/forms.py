import hmac

from django import forms
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction

from .models import OfficerProfile, User


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150, widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}), strip=False
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user = None

    def authenticate_user(self):
        """Return the user for valid credentials, else None. Does not log in."""
        self.user = authenticate(
            self.request,
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password"],
        )
        return self.user


class RegistrationForm(UserCreationForm):
    """Create-account form shared by every actor (REQ-AUTH-001/002/003).

    Subclasses set ``role``. Django's password validators (configured in settings)
    enforce the SRS password policy; username/e-mail uniqueness is checked here.
    """

    role = User.Role.CITIZEN

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Letters, digits and @/./+/-/_ only."
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["password1"].help_text = (
            "At least 8 characters, with letters and numbers; not too common, "
            "not all digits, and not similar to your personal details."
        )
        self.fields["password2"].help_text = "Enter the same password again."

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this e-mail address already exists.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.role
        user.email = self.cleaned_data["email"]
        user.save()
        self.save_role_profile(user)
        return user

    def save_role_profile(self, user):
        """Hook for role-specific rows (e.g. OfficerProfile)."""


class CitizenRegistrationForm(RegistrationForm):
    role = User.Role.CITIZEN


class _CodeProtectedForm(RegistrationForm):
    """Privileged roles must present the registration code issued by the operator."""

    registration_code = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
        strip=True,
    )
    expected_code_setting = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["registration_code"].help_text = "Issued to you by the system operator."

    def clean_registration_code(self):
        supplied = self.cleaned_data["registration_code"]
        expected = getattr(settings, self.expected_code_setting)
        if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise forms.ValidationError("Invalid registration code.")
        return supplied


class OfficerRegistrationForm(_CodeProtectedForm):
    role = User.Role.OFFICER
    expected_code_setting = "OFFICER_REGISTRATION_CODE"

    department = forms.CharField(max_length=100, initial="General")

    def save_role_profile(self, user):
        OfficerProfile.objects.create(user=user, department=self.cleaned_data["department"].strip())


class AdminRegistrationForm(_CodeProtectedForm):
    role = User.Role.ADMIN
    expected_code_setting = "ADMIN_REGISTRATION_CODE"
