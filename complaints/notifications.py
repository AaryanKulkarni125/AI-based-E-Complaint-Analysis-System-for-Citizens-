"""E-mail and SMS notifications (REQ-NOT-001..005) with persistent delivery logging and retries.

Failures are swallowed and logged in NotificationLog: an outage must never block
a complaint from being filed or updated (REQ-NOT-005).
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def _send(to, subject, body, complaint=None, channel="email"):
    if not to:
        return None
    from .models import NotificationLog

    log_entry = NotificationLog.objects.create(
        complaint=complaint,
        recipient=to,
        channel=channel,
        subject=subject,
        message=body,
        status="pending",
    )

    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        log_entry.status = "sent"
        log_entry.save(update_fields=["status"])
        return log_entry
    except Exception as exc:  # deliberately broad - notification outage shouldn't crash caller
        logger.exception("Could not send notification to %s: %s", to, exc)
        log_entry.status = "failed"
        log_entry.error_message = str(exc)
        log_entry.save(update_fields=["status", "error_message"])
        return log_entry


def retry_failed_notifications(limit=20):
    """Retry failed notifications up to MAX_RETRIES times (REQ-NOT-004)."""
    from .models import NotificationLog

    failed_logs = NotificationLog.objects.filter(
        status="failed", retry_count__lt=MAX_RETRIES
    ).order_by("timestamp")[:limit]

    retried_count = 0
    for entry in failed_logs:
        entry.retry_count += 1
        try:
            send_mail(
                entry.subject,
                entry.message,
                settings.DEFAULT_FROM_EMAIL,
                [entry.recipient],
                fail_silently=False,
            )
            entry.status = "sent"
            entry.error_message = ""
        except Exception as exc:
            logger.warning("Retry %d failed for notification %d: %s", entry.retry_count, entry.id, exc)
            entry.error_message = str(exc)
        entry.save(update_fields=["status", "retry_count", "error_message"])
        retried_count += 1
    return retried_count


def notify_citizen_received(complaint):
    _send(
        complaint.citizen.email,
        f"Complaint {complaint.reference} received",
        f"Hello {complaint.citizen.get_full_name() or complaint.citizen.username},\n\n"
        f"We have received your complaint. Your tracking ID is {complaint.reference}.\n"
        f"Category: {complaint.category.name if complaint.category else 'General'}\n"
        f"Priority: {complaint.get_priority_display()}\n\n"
        "You can follow its progress any time from your dashboard.\n",
        complaint=complaint,
    )


def notify_officer_assigned(complaint, reassigned=False, reason=""):
    officer = complaint.assigned_officer
    if officer:
        subj = f"{'Reassigned' if reassigned else 'New'} complaint assigned: {complaint.reference}"
        body = (
            f"Hello {officer.get_full_name() or officer.username},\n\n"
            f"Complaint {complaint.reference} has been assigned to you.\n"
            f"Location: {complaint.location} (Ward: {complaint.ward})\n"
            f"Category: {complaint.category.name if complaint.category else 'General'}\n"
            f"Priority: {complaint.get_priority_display()}\n"
            + (f"Reassignment reason: {reason}\n" if reason else "")
            + f"\nDescription:\n{complaint.description}\n"
        )
        _send(officer.email, subj, body, complaint=complaint)


def notify_citizen_status(complaint, note=""):
    _send(
        complaint.citizen.email,
        f"Complaint {complaint.reference}: {complaint.get_status_display()}",
        f"Hello {complaint.citizen.get_full_name() or complaint.citizen.username},\n\n"
        f"The status of your complaint {complaint.reference} is now "
        f"\"{complaint.get_status_display()}\".\n"
        + (f"\nOfficer remarks: {note}\n" if note else "")
        + "\nPlease visit the portal to view complete details or submit feedback once resolved.\n",
        complaint=complaint,
    )


def notify_officer_reopened(complaint, reason=""):
    officer = complaint.assigned_officer
    if officer:
        _send(
            officer.email,
            f"Complaint REOPENED: {complaint.reference}",
            f"Hello {officer.get_full_name() or officer.username},\n\n"
            f"Complaint {complaint.reference} has been reopened by the citizen.\n"
            f"Reason: {reason}\n\n"
            "Please review and take necessary action.\n",
            complaint=complaint,
        )
