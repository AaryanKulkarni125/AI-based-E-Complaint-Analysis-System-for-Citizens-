from django.contrib import admin

from .models import (
    AIOverrideLog,
    AssignmentLog,
    Attachment,
    Category,
    Complaint,
    Feedback,
    NotificationLog,
    StatusHistory,
)


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ("original_name", "content_type", "size", "uploaded_at")


class HistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "note", "timestamp")
    can_delete = False


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "citizen", "category", "ward", "status", "priority",
        "assigned_officer", "is_sla_breached", "submitted_at"
    )
    list_filter = ("status", "priority", "ward", "category")
    search_fields = ("description", "location")
    inlines = [AttachmentInline, HistoryInline]

    def has_delete_permission(self, request, obj=None):
        return False  # REQ-WFL-006: complaints are never deleted


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "department_name", "sla_hours")


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("complaint", "citizen", "rating", "created_at")
    list_filter = ("rating",)


@admin.register(AssignmentLog)
class AssignmentLogAdmin(admin.ModelAdmin):
    list_display = ("complaint", "from_officer", "to_officer", "assigned_by", "timestamp")
    readonly_fields = ("timestamp",)


@admin.register(AIOverrideLog)
class AIOverrideLogAdmin(admin.ModelAdmin):
    list_display = ("complaint", "original_category", "corrected_category", "actor", "timestamp")
    readonly_fields = ("timestamp",)


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("recipient", "channel", "subject", "status", "retry_count", "timestamp")
    list_filter = ("status", "channel")
    readonly_fields = ("timestamp",)
