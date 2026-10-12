import math
import random
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from complaints.models import Complaint

from .forms import (
    AdminRegistrationForm,
    CitizenRegistrationForm,
    CustomPasswordChangeForm,
    LoginForm,
    OfficerRegistrationForm,
    OTPRequestForm,
    OTPVerifyForm,
    PasswordResetRequestForm,
    UserProfileForm,
)
from .models import LoginAudit, OTPToken, User
from .security import client_ip, lockout_remaining, record_attempt


def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    form = LoginForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]

        remaining = lockout_remaining(username)
        if remaining is not None:
            record_attempt(request, username, LoginAudit.Outcome.LOCKED)
            minutes = max(1, math.ceil(remaining.total_seconds() / 60))
            form.add_error(
                None,
                f"Too many failed attempts. This account is locked for another {minutes} minute(s).",
            )
        else:
            user = form.authenticate_user()
            if user is None:
                record_attempt(request, username, LoginAudit.Outcome.FAILED)
                # Same message for unknown user / wrong password / deactivated account.
                form.add_error(None, "Incorrect username or password.")
            else:
                record_attempt(request, username, LoginAudit.Outcome.SUCCESS, user=user)
                login(request, user)
                next_url = request.POST.get("next") or request.GET.get("next")
                if next_url and url_has_allowed_host_and_scheme(
                    next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
                ):
                    return redirect(next_url)
                return redirect("accounts:dashboard")

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


def otp_login_request(request):
    """Initiate citizen OTP login (REQ-AUTH / SRS Section 4.1)."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    form = OTPRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if user and user.is_active:
            # Generate 6-digit OTP code
            code = f"{random.randint(100000, 999999):06d}"
            expires = timezone.now() + timedelta(minutes=10)
            OTPToken.objects.create(user=user, code=code, expires_at=expires)

            # Store pending user in session
            request.session["_otp_pending_user_id"] = user.pk

            # Dispatch notification / email
            send_mail(
                "Your Grievance Portal Login OTP",
                f"Hello {user.get_full_name() or user.username},\n\nYour 6-digit one-time password (OTP) is: {code}\n"
                "This code is valid for 10 minutes. Do not share it with anyone.\n",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )

            messages.info(
                request,
                f"A 6-digit verification code has been generated and sent to {user.email}.",
            )
            return redirect("accounts:otp_verify")
        else:
            # Mask user existence
            messages.info(
                request,
                "If an active account exists with the provided details, an OTP has been sent.",
            )

    return render(request, "accounts/otp_request.html", {"form": form})


def otp_login_verify(request):
    """Verify citizen OTP code and establish authenticated session."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    user_id = request.session.get("_otp_pending_user_id")
    if not user_id:
        messages.error(request, "Please request an OTP first.")
        return redirect("accounts:otp_request")

    user = get_object_or_404(User, pk=user_id)
    form = OTPVerifyForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["otp_code"].strip()
        token = OTPToken.objects.filter(
            user=user, code=code, is_used=False, expires_at__gte=timezone.now()
        ).first()

        if token:
            token.is_used = True
            token.save(update_fields=["is_used"])
            request.session.pop("_otp_pending_user_id", None)

            record_attempt(request, user.username, LoginAudit.Outcome.SUCCESS, user=user)
            login(request, user)
            messages.success(request, f"Welcome, {user.get_full_name() or user.username}!")
            return redirect("accounts:dashboard")
        else:
            record_attempt(request, user.username, LoginAudit.Outcome.FAILED)
            form.add_error("otp_code", "Invalid or expired verification code.")

    return render(request, "accounts/otp_verify.html", {"form": form, "user": user})


@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("accounts:login")


@login_required
def dashboard(request):
    user = request.user
    context = {}
    if user.is_system_admin:
        all_c = Complaint.objects.all()
        context.update(
            user_counts={
                "citizens": User.objects.filter(role=User.Role.CITIZEN).count(),
                "officers": User.objects.filter(role=User.Role.OFFICER).count(),
                "admins": User.objects.filter(role=User.Role.ADMIN).count(),
            },
            complaint_counts={
                "total": all_c.count(),
                "open": all_c.exclude(status__in=["resolved", "closed"]).count(),
                "resolved": all_c.filter(status="resolved").count(),
                "closed": all_c.filter(status="closed").count(),
                "reopened": all_c.filter(status="reopened").count(),
                "needs_review": all_c.filter(needs_review=True).count(),
            },
            recent_logins=LoginAudit.objects.select_related("user")[:10],
            recent_complaints=all_c[:5],
        )
        template = "accounts/dashboard_admin.html"
    elif user.is_officer:
        mine = Complaint.objects.filter(assigned_officer=user)
        context.update(
            workload=user.officer_profile.workload,
            resolved_count=mine.filter(status__in=["resolved", "closed"]).count(),
            pending_count=mine.exclude(status__in=["resolved", "closed"]).count(),
            recent=mine.order_by("-updated_at")[:5],
        )
        template = "accounts/dashboard_officer.html"
    else:
        mine = Complaint.objects.filter(citizen=user)
        context.update(
            open_count=mine.exclude(status__in=["resolved", "closed"]).count(),
            resolved_count=mine.filter(status__in=["resolved", "closed"]).count(),
            recent=mine[:5],
        )
        template = "accounts/dashboard_citizen.html"
    return render(request, template, context)


@login_required
def profile_view(request):
    """View and edit user profile (REQ-PRF-001..004)."""
    user = request.user
    form = UserProfileForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated successfully.")
        return redirect("accounts:profile")

    return render(request, "accounts/profile.html", {"form": form, "user": user})


@login_required
def password_change_view(request):
    """Change user password enforcing policy."""
    user = request.user
    form = CustomPasswordChangeForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        new_pwd = form.cleaned_data["new_password1"]
        user.set_password(new_pwd)
        user.save()
        update_session_auth_hash(request, user)  # Keep user logged in
        messages.success(request, "Your password has been changed successfully.")
        return redirect("accounts:profile")

    return render(request, "accounts/password_change.html", {"form": form})


def password_reset_request_view(request):
    """Request password reset link (REQ-AUTH-007)."""
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip()
        user = User.objects.filter(email__iexact=email).first()
        if user:
            send_mail(
                "Password Reset Request — E-Complaint System",
                f"Hello {user.get_full_name() or user.username},\n\n"
                "A password reset request was received for your account.\n"
                "In this development environment, please use the account profile or admin tools to reset credentials.\n",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )
        messages.info(
            request,
            "If an account with that email exists, reset instructions have been dispatched.",
        )
        return redirect("accounts:login")

    return render(request, "accounts/password_reset.html", {"form": form})


REGISTRATION_FORMS = {
    "citizen": (CitizenRegistrationForm, "Citizen"),
    "officer": (OfficerRegistrationForm, "Officer"),
    "admin": (AdminRegistrationForm, "System Administrator"),
}
CODE_GUESS_LIMIT = 10
CODE_GUESS_WINDOW = 15 * 60


def register_choice(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    return render(request, "accounts/register_choice.html")


def register(request, role):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    if role not in REGISTRATION_FORMS:
        raise Http404
    form_class, role_label = REGISTRATION_FORMS[role]
    needs_code = role != "citizen"

    throttle_key = f"regcode-fail:{client_ip(request)}"
    if needs_code and request.method == "POST" and cache.get(throttle_key, 0) >= CODE_GUESS_LIMIT:
        messages.error(request, "Too many invalid registration codes. Please try again later.")
        return redirect("accounts:register", role=role)

    form = form_class(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.save()
            messages.success(
                request, f"{role_label} account created for {user.username}. You can now log in."
            )
            return redirect("accounts:login")
        if needs_code and "registration_code" in form.errors:
            cache.set(throttle_key, cache.get(throttle_key, 0) + 1, CODE_GUESS_WINDOW)

    return render(
        request,
        "accounts/register.html",
        {"form": form, "role": role, "role_label": role_label, "needs_code": needs_code},
    )
