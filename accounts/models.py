from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Single user table for every actor (class diagram: User + role)."""

    class Role(models.TextChoices):
        CITIZEN = "citizen", "Citizen"
        OFFICER = "officer", "Officer"
        ADMIN = "admin", "System Administrator"

    # REQ-AUTH-003: e-mail must be unique across accounts.
    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CITIZEN)

    class Meta:
        ordering = ["id"]

    @property
    def is_citizen(self):
        return self.role == self.Role.CITIZEN

    @property
    def is_officer(self):
        return self.role == self.Role.OFFICER

    @property
    def is_system_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def account_status(self):
        return "Active" if self.is_active else "Deactivated"

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class OfficerProfile(models.Model):
    """Officer-specific attributes (class diagram: Officer)."""

    class Availability(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="officer_profile")
    department = models.CharField(max_length=100, default="General")
    availability_status = models.CharField(
        max_length=10, choices=Availability.choices, default=Availability.ACTIVE
    )

    @property
    def workload(self):
        """Open complaints currently assigned (computed so it never drifts)."""
        return self.user.assigned_complaints.exclude(
            status__in=["resolved", "closed"]
        ).count()

    def __str__(self):
        return f"Officer {self.user.username} - {self.department}"


class LoginAudit(models.Model):
    """REQ-AUTH-009 / REQ-SEC-004: every login attempt is recorded."""

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        LOCKED = "locked", "Rejected (account locked)"

    username = models.CharField(max_length=150)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M:%S} {self.username} {self.outcome}"
