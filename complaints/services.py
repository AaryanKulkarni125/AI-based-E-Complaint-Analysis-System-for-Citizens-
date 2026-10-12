"""Complaint workflow logic, kept out of the views so AI, admin, and API modules reuse it."""

from datetime import timedelta
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import OfficerProfile, User

from . import ai, notifications
from .forms import MIN_REMARKS
from .models import (
    AIOverrideLog,
    AssignmentLog,
    Attachment,
    Category,
    Complaint,
    Feedback,
    StatusHistory,
)
from .validators import validate_attachment


class WorkflowError(Exception):
    """Raised when a requested status change or action breaks the workflow rules."""


def record_history(complaint, to_status, changed_by=None, note="", from_status=""):
    return StatusHistory.objects.create(
        complaint=complaint,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        note=note,
    )


def find_potential_duplicate(ward, category, description, within_days=7):
    """Detect if a similar complaint exists within the given ward and timeframe (REQ-GRV-4)."""
    since = timezone.now() - timedelta(days=within_days)
    candidates = Complaint.objects.filter(
        submitted_at__gte=since
    ).exclude(status__in=[Complaint.Status.CLOSED])

    if ward:
        candidates = candidates.filter(ward__iexact=ward.strip())
    if category:
        candidates = candidates.filter(category=category)

    desc_words = {w.lower() for w in description.split() if len(w) > 3}
    if not desc_words:
        return None

    for cand in candidates:
        cand_words = {w.lower() for w in cand.description.split() if len(w) > 3}
        if cand_words:
            overlap = len(desc_words.intersection(cand_words)) / max(len(desc_words), 1)
            if overlap >= 0.5:
                return cand
    return None


def pick_officer(category=None):
    """Pick least-loaded active officer.

    Prefers officers whose department matches the complaint's category department (REQ-WFL-002, REQ-ASGN-1).
    Falls back to any active officer if no matching department officer is active.
    """
    open_count = Count(
        "user__assigned_complaints",
        filter=~Q(user__assigned_complaints__status__in=[Complaint.Status.RESOLVED, Complaint.Status.CLOSED]),
    )
    base_qs = OfficerProfile.objects.filter(
        availability_status=OfficerProfile.Availability.ACTIVE,
        user__is_active=True,
        user__role=User.Role.OFFICER,
    ).annotate(open_count=open_count)

    # 1. Try matching department if category has one
    if category and category.department_name:
        dept_match = (
            base_qs.filter(department__iexact=category.department_name)
            .order_by("open_count", "user_id")
            .select_related("user")
            .first()
        )
        if dept_match:
            return dept_match.user

    # 2. Fall back to least-loaded active officer across any department
    profile = base_qs.order_by("open_count", "user_id").select_related("user").first()
    return profile.user if profile else None


def route_complaint(complaint):
    """Assign an unassigned complaint to an active officer. Returns True if assigned."""
    officer = pick_officer(category=complaint.category)
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


@transaction.atomic
def create_complaint(
    citizen,
    description,
    location,
    files=(),
    ward="Ward 1",
    latitude=None,
    longitude=None,
    category=None,
):
    """Persist a new complaint with AI analysis, duplicate detection, attachments, and routing."""
    # 1. Run AI analysis on the description (REQ-AI-001..003)
    predicted_cat_name, priority, confidence, needs_review = ai.classify_text(description)

    # Use explicitly passed category if valid, else match AI prediction from DB
    if not category and predicted_cat_name:
        category = Category.objects.filter(name__iexact=predicted_cat_name).first()

    # 2. Duplicate detection (REQ-GRV-4)
    potential_dup = find_potential_duplicate(ward, category, description)
    is_duplicate = potential_dup is not None
    duplicate_of = potential_dup

    # 3. Create complaint record
    complaint = Complaint.objects.create(
        citizen=citizen,
        description=description,
        location=location,
        ward=ward or "Ward 1",
        latitude=latitude,
        longitude=longitude,
        category=category,
        priority=priority,
        confidence_score=confidence,
        needs_review=needs_review,
        is_duplicate=is_duplicate,
        duplicate_of=duplicate_of,
    )

    # 4. Attachments
    for uploaded in files:
        Attachment.objects.create(
            complaint=complaint,
            file=uploaded,
            original_name=uploaded.name[:255],
            content_type=validate_attachment(uploaded),
            size=uploaded.size,
        )

    # 5. Record initial history
    record_history(complaint, Complaint.Status.SUBMITTED, changed_by=citizen, note="Complaint submitted")

    # 6. Route inside the same transaction; e-mails sent after commit
    route_complaint(complaint)
    transaction.on_commit(lambda: notifications.notify_citizen_received(complaint))
    return complaint


@transaction.atomic
def change_status(complaint, officer, new_status, remarks="", evidence=()):
    """Officer-driven status change (REQ-WFL-003, REQ-RES-001..003/005).

    Only the assigned officer may act, and only along Assigned -> Acknowledged ->
    In Progress -> Resolved (or Reopened -> In Progress / Acknowledged). Resolving needs remarks of at least MIN_REMARKS characters.
    """
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


@transaction.atomic
def admin_reassign_complaint(complaint, new_officer, admin_user, reason):
    """Admin manual reassignment with mandatory audit trail (REQ-ASGN-2)."""
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("A mandatory reason remark is required to reassign a complaint.")
    if not admin_user.is_system_admin:
        raise WorkflowError("Only administrators may reassign complaints.")
    if new_officer.role != User.Role.OFFICER or not new_officer.is_active:
        raise WorkflowError("Assigned target must be an active officer.")

    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    old_officer = complaint.assigned_officer
    previous_status = complaint.status

    # Record assignment log
    AssignmentLog.objects.create(
        complaint=complaint,
        from_officer=old_officer,
        to_officer=new_officer,
        assigned_by=admin_user,
        reason=reason,
    )

    complaint.assigned_officer = new_officer
    if complaint.status == Complaint.Status.SUBMITTED:
        complaint.status = Complaint.Status.ASSIGNED

    complaint.save(update_fields=["assigned_officer", "status", "updated_at"])

    note_msg = f"Reassigned from {old_officer.username if old_officer else 'None'} to {new_officer.username}. Reason: {reason}"
    record_history(
        complaint,
        complaint.status,
        changed_by=admin_user,
        note=note_msg,
        from_status=previous_status,
    )

    transaction.on_commit(
        lambda: notifications.notify_officer_assigned(complaint, reassigned=True, reason=reason)
    )
    return complaint


@transaction.atomic
def admin_override_ai(complaint, new_category, new_priority, admin_user, reason=""):
    """Admin override of AI-predicted category and priority with audit logging (REQ-AI-004/005)."""
    if not admin_user.is_system_admin:
        raise WorkflowError("Only administrators can override AI predictions.")
    if new_priority not in Complaint.Priority.values:
        raise WorkflowError(f"Invalid priority: {new_priority}")

    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    orig_cat = complaint.category
    orig_prio = complaint.priority

    AIOverrideLog.objects.create(
        complaint=complaint,
        original_category=orig_cat,
        corrected_category=new_category,
        original_priority=orig_prio,
        corrected_priority=new_priority,
        actor=admin_user,
        reason=reason,
    )

    complaint.category = new_category
    complaint.priority = new_priority
    complaint.needs_review = False  # cleared after admin review
    complaint.save(update_fields=["category", "priority", "needs_review", "updated_at"])

    record_history(
        complaint,
        complaint.status,
        changed_by=admin_user,
        note=f"AI Override by Admin: Category='{new_category}', Priority='{new_priority}'. Reason: {reason}",
        from_status=complaint.status,
    )
    return complaint


@transaction.atomic
def admin_close_complaint(complaint, admin_user, remarks=""):
    """Admin closes a resolved complaint (REQ-RES-004 / SRS Section 4.5)."""
    if not admin_user.is_system_admin:
        raise WorkflowError("Only administrators can close complaints.")
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)

    if complaint.status != Complaint.Status.RESOLVED:
        raise WorkflowError("Only resolved complaints can be closed.")

    previous = complaint.status
    complaint.status = Complaint.Status.CLOSED
    complaint.closed_by = admin_user
    complaint.closed_at = timezone.now()
    complaint.closure_remarks = remarks
    complaint.save(update_fields=["status", "closed_by", "closed_at", "closure_remarks", "updated_at"])

    record_history(
        complaint,
        Complaint.Status.CLOSED,
        changed_by=admin_user,
        note=f"Complaint closed by admin: {remarks}" if remarks else "Complaint closed by admin",
        from_status=previous,
    )
    transaction.on_commit(lambda: notifications.notify_citizen_status(complaint, f"Closed: {remarks}"))
    return complaint


@transaction.atomic
def submit_citizen_feedback(complaint, citizen, rating, comments=""):
    """Citizen confirms resolution and submits satisfaction rating (REQ-FDBK-1)."""
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if complaint.citizen_id != citizen.pk:
        raise WorkflowError("Only the filing citizen can submit feedback for this complaint.")
    if complaint.status not in (Complaint.Status.RESOLVED, Complaint.Status.CLOSED):
        raise WorkflowError("Feedback can only be submitted for resolved or closed complaints.")

    feedback, _ = Feedback.objects.update_or_create(
        complaint=complaint,
        defaults={"citizen": citizen, "rating": int(rating), "comments": comments},
    )
    return feedback


@transaction.atomic
def reopen_complaint(complaint, actor, reason):
    """Citizen reopens an unsatisfied grievance within 7 days (REQ-FDBK-2)."""
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("A reason is required to reopen a complaint.")

    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    is_owner = complaint.citizen_id == actor.pk
    is_admin = actor.is_system_admin
    if not (is_owner or is_admin):
        raise WorkflowError("You are not authorized to reopen this complaint.")

    if not complaint.can_be_reopened and not is_admin:
        raise WorkflowError("Complaints can only be reopened within 7 days of resolution.")

    previous = complaint.status
    complaint.status = Complaint.Status.REOPENED
    complaint.save(update_fields=["status", "updated_at"])

    record_history(
        complaint,
        Complaint.Status.REOPENED,
        changed_by=actor,
        note=f"Reopened by {actor.username}: {reason}",
        from_status=previous,
    )
    transaction.on_commit(lambda: notifications.notify_officer_reopened(complaint, reason))
    return complaint
