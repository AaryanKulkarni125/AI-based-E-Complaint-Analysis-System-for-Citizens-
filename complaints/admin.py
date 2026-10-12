from django.contrib import admin

from .models import Attachment, Category, Complaint, StatusHistory


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
    list_display = ("reference", "citizen", "status", "priority", "assigned_officer", "submitted_at")
    list_filter = ("status", "priority")
    inlines = [AttachmentInline, HistoryInline]

    def has_delete_permission(self, request, obj=None):
        return False  # REQ-WFL-006: complaints are never deleted


admin.site.register(Category)
