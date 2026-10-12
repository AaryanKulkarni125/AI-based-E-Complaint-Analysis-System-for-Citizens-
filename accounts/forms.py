import hmac
import random
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.utils import timezone

from .models import OfficerProfile, OTPToken, User


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
    """Create-account form shared by every actor (REQ-AUTH-001/002/003)."""

    role = User.Role.CITIZEN

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False, help_text="Optional, for SMS/OTP notifications.")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone")

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
        user.phone = self.cleaned_data.get("phone", "")
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


class UserProfileForm(forms.ModelForm):
    """Profile editing form (REQ-PRF-001..004)."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Last name"}),
            "email": forms.EmailInput(attrs={"placeholder": "Email address"}),
            "phone": forms.TextInput(attrs={"placeholder": "Phone number"}),
        }

    def __init__(self, *args, **kwargs):
        self.instance_user = kwargs.get("instance")
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        qs = User.objects.filter(email__iexact=email)
        if self.instance_user:
            qs = qs.exclude(pk=self.instance_user.pk)
        if qs.exists():
            raise forms.ValidationError("This email address is already in use by another account.")
        return email


class CustomPasswordChangeForm(forms.Form):
    """Change password form enforcing current password validation and password policy."""

    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        label="Current Password",
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        label="New Password",
        help_text="At least 8 characters, letters and numbers.",
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        label="Confirm New Password",
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        curr = self.cleaned_data["current_password"]
        if not self.user.check_password(curr):
            raise forms.ValidationError("Current password is incorrect.")
        return curr

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password1")
        p2 = cleaned.get("new_password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("new_password2", "The two new passwords did not match.")
            else:
                password_validation.validate_password(p1, self.user)
        return cleaned


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        label="Registered Email Address",
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com"}),
    )


class OTPRequestForm(forms.Form):
    """Initiate citizen OTP login (REQ-AUTH / SRS 4.1)."""

    identifier = forms.CharField(
        label="Username, Email or Phone",
        widget=forms.TextInput(attrs={"placeholder": "Enter username, email or mobile number", "autofocus": True}),
    )

    def get_user(self):
        ident = self.cleaned_data["identifier"].strip()
        user = (
            User.objects.filter(username__iexact=ident).first()
            or User.objects.filter(email__iexact=ident).first()
            or (User.objects.filter(phone=ident).first() if ident else None)
        )
        return user


class OTPVerifyForm(forms.Form):
    """Verify citizen 6-digit OTP code."""

    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        label="6-Digit Verification Code",
        widget=forms.TextInput(attrs={"placeholder": "123456", "maxlength": "6", "autofocus": True}),
    )
