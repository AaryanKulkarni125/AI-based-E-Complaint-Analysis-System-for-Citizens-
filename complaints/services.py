"""Complaint workflow logic, kept out of the views so the AI/admin modules can reuse it."""

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import OfficerProfile, User

from . import notifications
from .forms import MIN_REMARKS
from .models import Attachment, Complaint, StatusHistory
from .validators import validate_attachment


def record_history(complaint, to_status, changed_by=None, note="", from_status=""):
    return StatusHistory.objects.create(
        complaint=complaint,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        note=note,
    )


@transaction.atomic
def create_complaint(citizen, description, location, files=()):
    """Persist a new complaint with its attachments and first history entry, then route it."""
    complaint = Complaint.objects.create(
        citizen=citizen, description=description, location=location
    )
    for uploaded in files:
        Attachment.objects.create(
            complaint=complaint,
            file=uploaded,
            original_name=uploaded.name[:255],
            content_type=validate_attachment(uploaded),
            size=uploaded.size,
        )
    record_history(complaint, Complaint.Status.SUBMITTED, changed_by=citizen, note="Complaint submitted")
    # Route inside the same transaction; e-mails are sent after commit.
    route_complaint(complaint)
    transaction.on_commit(lambda: notifications.notify_citizen_received(complaint))
    return complaint


def pick_officer():
    """Least-loaded active officer (ties broken by account age), or None.

    Placeholder for the AI/admin-driven routing that will replace it: for now every
    complaint goes to an officer who is currently active.
    """
    open_count = Count(
        "user__assigned_complaints",
        filter=~Q(user__assigned_complaints__status__in=[Complaint.Status.RESOLVED, Complaint.Status.CLOSED]),
    )
    profile = (
        OfficerProfile.objects.filter(
            availability_status=OfficerProfile.Availability.ACTIVE,
            user__is_active=True,
            user__role=User.Role.OFFICER,
        )
        .annotate(open_count=open_count)
        .order_by("open_count", "user_id")
        .select_related("user")
        .first()
    )
    return profile.user if profile else None


def route_complaint(complaint):
    """Assign an unassigned complaint to an active officer. Returns True if assigned."""
    officer = pick_officer()
    if officer is None:
        return False  # stays "Submitted"; picked up when an officer becomes active
    previous = complaint.status
    complaint.assigned_officer = officer
    complaint.status = Complaint.Status.ASSIGNED
    complaint.save(update_fields=["assigned_officer", "status", "updated_at"])
    record_history(
        complaint,
        Complaint.Status.ASSIGNED,
        note=f"Routed to officer {officer.get_full_name() or officer.username}",
        from_status=previous,
    )
    transaction.on_commit(lambda: notifications.notify_officer_assigned(complaint))
    return True


def assign_queued_complaints():
    """Route complaints that were waiting because no officer was active."""
    for complaint in Complaint.objects.filter(
        status=Complaint.Status.SUBMITTED, assigned_officer__isnull=True
    ).order_by("submitted_at", "id"):
        if not route_complaint(complaint):
            break


class WorkflowError(Exception):
    """Raised when a requested status change breaks the workflow rules."""


@transaction.atomic
def change_status(complaint, officer, new_status, remarks="", evidence=()):
    """Officer-driven status change (REQ-WFL-003, REQ-RES-001..003/005, business rules).

    Only the assigned officer may act, and only along Assigned -> Acknowledged ->
    In Progress -> Resolved. Resolving needs remarks of at least MIN_REMARKS characters.
    """
    # Lock the row so two concurrent updates can't both pass the transition check.
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)

    if complaint.assigned_officer_id != officer.pk:
        raise WorkflowError("You can only update complaints assigned to you.")
    if new_status not in complaint.next_officer_statuses:
        raise WorkflowError(
            f"A complaint that is \"{complaint.get_status_display()}\" cannot be moved to "
            f"\"{Complaint.Status(new_status).label}\"."
        )

    remarks = (remarks or "").strip()
    resolving = new_status == Complaint.Status.RESOLVED
    if resolving and len(remarks) < MIN_REMARKS:
        raise WorkflowError(
            f"Resolution remarks of at least {MIN_REMARKS} characters are required to resolve a complaint."
        )

    previous = complaint.status
    complaint.status = new_status
    update_fields = ["status", "updated_at"]
    if resolving:
        now = timezone.now()
        complaint.resolution_remarks = remarks
        complaint.resolved_by = officer
        complaint.resolved_at = now
        complaint.resolution_time = now - complaint.submitted_at
        update_fields += ["resolution_remarks", "resolved_by", "resolved_at", "resolution_time"]
        for uploaded in evidence:
            Attachment.objects.create(
                complaint=complaint,
                file=uploaded,
                original_name=uploaded.name[:255],
                content_type=validate_attachment(uploaded),
                size=uploaded.size,
                is_resolution_evidence=True,
            )
    complaint.save(update_fields=update_fields)
    record_history(complaint, new_status, changed_by=officer, note=remarks, from_status=previous)
    transaction.on_commit(lambda: notifications.notify_citizen_status(complaint, remarks))
    return complaint
