import math

from django.contrib import messages
from django.core.cache import cache
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from complaints.models import Complaint

from .forms import AdminRegistrationForm, CitizenRegistrationForm, LoginForm, OfficerRegistrationForm
from .models import LoginAudit, User
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
        context.update(
            user_counts={
                "citizens": User.objects.filter(role=User.Role.CITIZEN).count(),
                "officers": User.objects.filter(role=User.Role.OFFICER).count(),
                "admins": User.objects.filter(role=User.Role.ADMIN).count(),
            },
            recent_logins=LoginAudit.objects.select_related("user")[:10],
        )
        template = "accounts/dashboard_admin.html"
    elif user.is_officer:
        mine = Complaint.objects.filter(assigned_officer=user)
        context.update(
            workload=user.officer_profile.workload,
            resolved_count=mine.filter(status__in=["resolved", "closed"]).count(),
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


REGISTRATION_FORMS = {
    "citizen": (CitizenRegistrationForm, "Citizen"),
    "officer": (OfficerRegistrationForm, "Officer"),
    "admin": (AdminRegistrationForm, "System Administrator"),
}
CODE_GUESS_LIMIT = 10          # bad registration codes allowed per IP ...
CODE_GUESS_WINDOW = 15 * 60    # ... per this many seconds


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
