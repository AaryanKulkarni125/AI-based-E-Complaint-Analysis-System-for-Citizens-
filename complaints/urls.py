from django.urls import path

from . import views

app_name = "complaints"

urlpatterns = [
    path("submit/", views.submit, name="submit"),
    path("confirmation/<int:pk>/", views.confirmation, name="confirmation"),
    path("mine/", views.my_list, name="my_list"),
    path("assigned/", views.officer_list, name="officer_list"),
    path("<int:pk>/", views.detail, name="detail"),
    path("attachments/<int:pk>/", views.download_attachment, name="attachment"),

    # Administrator workflows
    path("admin/all/", views.admin_complaint_list, name="admin_complaint_list"),
    path("admin/map/", views.admin_map_view, name="admin_map_view"),
    path("admin/analytics/", views.admin_analytics, name="admin_analytics"),
    path("admin/export/csv/", views.export_csv, name="export_csv"),
    path("admin/export/pdf/", views.export_pdf, name="export_pdf"),
    path("admin/officers/", views.admin_officer_roster, name="admin_officer_roster"),
    path("admin/officers/<int:pk>/toggle/", views.admin_toggle_officer_status, name="admin_toggle_officer_status"),
    path("admin/notifications/", views.admin_notification_logs, name="admin_notification_logs"),
    path("admin/notifications/retry/", views.admin_retry_notifications, name="admin_retry_notifications"),
]
