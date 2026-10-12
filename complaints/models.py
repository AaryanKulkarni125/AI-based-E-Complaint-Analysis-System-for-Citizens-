from datetime import timedelta
import uuid
from pathlib import PurePath

from django.conf import settings
from django.db import models
from django.utils import timezone


class Category(models.Model):
    """Department / complaint category. Filled in by the AI engine later (class diagram: Category)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    department_name = models.CharField(max_length=100, default="General")
    sla_hours = models.PositiveIntegerField(default=48, help_text="SLA resolution window in hours")

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Complaint(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        ASSIGNED = "assigned", "Assigned"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"
        REOPENED = "reopened", "Reopened"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    # Allowed officer-driven transitions. Order mirrors SRS REQ-WFL-003 (no skipping);
    # "Acknowledged" is the officer's explicit acceptance step. Closing is admin-only.
    OFFICER_TRANSITIONS = {
        Status.ASSIGNED: [Status.ACKNOWLEDGED],
        Status.ACKNOWLEDGED: [Status.IN_PROGRESS],
        Status.IN_PROGRESS: [Status.RESOLVED],
        Status.REOPENED: [Status.ACKNOWLEDGED, Status.IN_PROGRESS],
    }

    citizen = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="complaints"
    )
    description = models.TextField()
    location = models.CharField(max_length=255)
    ward = models.CharField(max_length=50, blank=True, default="Ward 1")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.SUBMITTED)

    # Filled by the AI categorization engine or override
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    priority = models.CharField(max_length=6, choices=Priority.choices, default=Priority.MEDIUM)
    confidence_score = models.FloatField(null=True, blank=True)
    needs_review = models.BooleanField(default=False)

    # Duplicate detection (REQ-GRV-4)
    is_duplicate = models.BooleanField(default=False)
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates"
    )

    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_complaints",
    )

    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    resolution_remarks = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_complaints",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_time = models.DurationField(null=True, blank=True)

    # Admin closure
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="closed_complaints",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at", "-id"]
        indexes = [models.Index(fields=["status"])]

    @property
    def reference(self):
        """Unique, never-reused tracking ID derived from the auto-increment key."""
        return f"CMP-{self.pk:06d}"

    @classmethod
    def pk_from_reference(cls, text):
        text = (text or "").strip().upper()
        if text.startswith("CMP-") and text[4:].isdigit():
            return int(text[4:])
        return None

    @property
    def is_open(self):
        return self.status not in (self.Status.RESOLVED, self.Status.CLOSED)

    @property
    def next_officer_statuses(self):
        return self.OFFICER_TRANSITIONS.get(self.status, [])

    @property
    def is_sla_breached(self):
        sla_h = self.category.sla_hours if self.category else 48
        if self.status in [self.Status.RESOLVED, self.Status.CLOSED]:
            if self.resolution_time:
                return self.resolution_time.total_seconds() > (sla_h * 3600)
            if self.resolved_at and self.submitted_at:
                return (self.resolved_at - self.submitted_at).total_seconds() > (sla_h * 3600)
            return False
        return (timezone.now() - self.submitted_at).total_seconds() > (sla_h * 3600)

    @property
    def sla_remaining_hours(self):
        sla_h = self.category.sla_hours if self.category else 48
        if self.status in [self.Status.RESOLVED, self.Status.CLOSED]:
            return 0.0
        elapsed_sec = (timezone.now() - self.submitted_at).total_seconds()
        remaining = sla_h - (elapsed_sec / 3600)
        return max(0.0, round(remaining, 1))

    @property
    def can_be_reopened(self):
        """Citizen can reopen within 7 days of resolution if not closed."""
        if self.status != self.Status.RESOLVED:
            return False
        if not self.resolved_at:
            return True
        return timezone.now() <= (self.resolved_at + timedelta(days=7))

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"


def attachment_path(instance, filename):
    # Random name on disk: no user-controlled path components, no collisions.
    return f"attachments/{uuid.uuid4().hex}{PurePath(filename).suffix.lower()}"


class Attachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_path)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # True when the officer attached it as resolution evidence (REQ-RES-002).
    is_resolution_evidence = models.BooleanField(default=False)

    def __str__(self):
        return self.original_name


class StatusHistory(models.Model):
    """Chronological record of every status change / assignment (REQ-TRK-003, REQ-WFL-005)."""

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15, choices=Complaint.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    note = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp", "id"]
        verbose_name_plural = "status history"

    def __str__(self):
        return f"{self.complaint.reference}: {self.from_status or '-'} -> {self.to_status}"


class Feedback(models.Model):
    """Citizen satisfaction rating and feedback (REQ-FDBK-1..3)."""

    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE, related_name="feedback")
    citizen = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedbacks"
    )
    rating = models.PositiveSmallIntegerField(
        choices=[(1, "1 - Very Unsatisfied"), (2, "2 - Unsatisfied"), (3, "3 - Neutral"), (4, "4 - Satisfied"), (5, "5 - Very Satisfied")],
        default=5,
    )
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Feedback for {self.complaint.reference}: {self.rating} stars"


class AssignmentLog(models.Model):
    """Audit log of manual reassignments by administrators (REQ-ASGN-2)."""

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="assignment_logs")
    from_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    reason = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"Reassignment on {self.complaint.reference} by {self.assigned_by.username}"


class AIOverrideLog(models.Model):
    """Audit log of administrative overrides on AI predicted category & priority (REQ-AI-004/005)."""

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="ai_override_logs")
    original_category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    corrected_category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    original_priority = models.CharField(max_length=6)
    corrected_priority = models.CharField(max_length=6)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    reason = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"AI Override on {self.complaint.reference} by {self.actor.username}"


class NotificationLog(models.Model):
    """Delivery log for email/SMS notifications with retry history (REQ-NOT-004/005)."""

    complaint = models.ForeignKey(
        Complaint, null=True, blank=True, on_delete=models.SET_NULL, related_name="notification_logs"
    )
    recipient = models.CharField(max_length=255)
    channel = models.CharField(
        max_length=10,
        choices=[("email", "Email"), ("sms", "SMS"), ("push", "Push Notification")],
        default="email",
    )
    subject = models.CharField(max_length=255, blank=True)
    message = models.TextField()
    status = models.CharField(
        max_length=15,
        choices=[("sent", "Sent"), ("failed", "Failed"), ("pending", "Pending")],
        default="pending",
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.channel.upper()} to {self.recipient} [{self.status}]"
