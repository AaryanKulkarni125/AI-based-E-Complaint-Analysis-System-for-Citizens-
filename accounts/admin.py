from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import LoginAudit, OfficerProfile, OTPToken, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Custom Role & Details", {"fields": ("role", "phone")}),
    )


@admin.register(OfficerProfile)
class OfficerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "department", "availability_status", "workload")
    list_filter = ("availability_status", "department")


@admin.register(LoginAudit)
class LoginAuditAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "username", "outcome", "ip_address")
    list_filter = ("outcome",)
    readonly_fields = ("timestamp", "username", "outcome", "ip_address", "user")


@admin.register(OTPToken)
class OTPTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "code", "created_at", "expires_at", "is_used")
    list_filter = ("is_used",)
    readonly_fields = ("created_at",)
