"""Login throttling (REQ-AUTH-006) and audit helpers (REQ-AUTH-009)."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import LoginAudit


def client_ip(request):
    # REMOTE_ADDR only: X-Forwarded-For is client-controlled unless a trusted proxy sets it.
    return request.META.get("REMOTE_ADDR")


def lockout_remaining(username):
    """Return a timedelta until the account unlocks, or None if not locked.

    Locked when the latest N failed attempts since the last successful login all
    fall inside the failure window and the newest one is within the lockout time.
    Rejected attempts made while locked are logged as LOCKED and do not extend it.
    """
    n = settings.LOGIN_MAX_FAILED_ATTEMPTS
    window = timedelta(minutes=settings.LOGIN_FAILURE_WINDOW_MINUTES)
    lockout = timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)

    attempts = LoginAudit.objects.filter(username__iexact=username).exclude(
        outcome=LoginAudit.Outcome.LOCKED
    )
    last_success = (
        attempts.filter(outcome=LoginAudit.Outcome.SUCCESS).values_list("timestamp", flat=True).first()
    )
    failures = attempts.filter(outcome=LoginAudit.Outcome.FAILED)
    if last_success:
        failures = failures.filter(timestamp__gt=last_success)
    recent = list(failures.values_list("timestamp", flat=True)[:n])  # newest first
    if len(recent) < n:
        return None
    newest, oldest = recent[0], recent[-1]
    if newest - oldest > window:
        return None
    unlock_at = newest + lockout
    now = timezone.now()
    return unlock_at - now if unlock_at > now else None


def record_attempt(request, username, outcome, user=None):
    LoginAudit.objects.create(
        username=username[:150],
        user=user,
        outcome=outcome,
        ip_address=client_ip(request),
    )
