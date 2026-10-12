import uuid
from pathlib import PurePath

from django.conf import settings
from django.db import models


class Category(models.Model):
    """Department / complaint category. Filled in by the AI engine later (class diagram: Category)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

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
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    # Allowed officer-driven transitions. Order mirrors SRS REQ-WFL-003 (no skipping);
    # "Acknowledged" is the officer's explicit acceptance step. Closing is admin-only (later).
    OFFICER_TRANSITIONS = {
        Status.ASSIGNED: [Status.ACKNOWLEDGED],
        Status.ACKNOWLEDGED: [Status.IN_PROGRESS],
        Status.IN_PROGRESS: [Status.RESOLVED],
    }

    citizen = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="complaints"
    )
    description = models.TextField()
    location = models.CharField(max_length=255)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.SUBMITTED)

    # Filled by the AI categorization engine later; until then they stay empty / default.
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    priority = models.CharField(max_length=6, choices=Priority.choices, default=Priority.MEDIUM)
    confidence_score = models.FloatField(null=True, blank=True)

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
