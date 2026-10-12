"""E-mail notifications (REQ-NOT-001/002/003). Console backend in development.

Failures are swallowed and logged: a mail outage must never block a complaint from
being filed or updated. (Retry + delivery log, REQ-NOT-004/005, is a later module.)
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _send(to, subject, body):
    if not to:
        return
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
    except Exception:  # noqa: BLE001 - deliberately broad, see module docstring
        logger.exception("Could not send notification e-mail to %s", to)


def notify_citizen_received(complaint):
    _send(
        complaint.citizen.email,
        f"Complaint {complaint.reference} received",
        f"Hello {complaint.citizen.get_full_name() or complaint.citizen.username},\n\n"
        f"We have received your complaint. Your tracking ID is {complaint.reference}.\n"
        "You can follow its progress any time from your dashboard.\n",
    )


def notify_officer_assigned(complaint):
    officer = complaint.assigned_officer
    if officer:
        _send(
            officer.email,
            f"New complaint assigned: {complaint.reference}",
            f"Hello {officer.get_full_name() or officer.username},\n\n"
            f"Complaint {complaint.reference} has been assigned to you.\n"
            f"Location: {complaint.location}\n\n{complaint.description}\n",
        )


def notify_citizen_status(complaint, note=""):
    _send(
        complaint.citizen.email,
        f"Complaint {complaint.reference}: {complaint.get_status_display()}",
        f"Hello {complaint.citizen.get_full_name() or complaint.citizen.username},\n\n"
        f"The status of your complaint {complaint.reference} is now "
        f"\"{complaint.get_status_display()}\".\n"
        + (f"\nOfficer remarks: {note}\n" if note else ""),
    )
