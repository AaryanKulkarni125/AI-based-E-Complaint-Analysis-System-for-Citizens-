from django.contrib import admin
from django.urls import include, path

from complaints import api_views
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("complaints/", include("complaints.urls")),
    path("django-admin/", admin.site.urls),

    # --- Centralized REST API endpoints ---
    path("api/health/", views.health, name="health"),
    path("api/complaints/", api_views.complaints_collection, name="api_complaints"),
    path("api/complaints/<int:pk>/", api_views.complaint_detail, name="api_complaint_detail"),
    path("api/complaints/<int:pk>/status/", api_views.update_status_api, name="api_update_status"),
    path("api/complaints/<int:pk>/assign/", api_views.reassign_api, name="api_reassign"),
    path("api/complaints/<int:pk>/override-ai/", api_views.override_ai_api, name="api_override_ai"),
    path("api/complaints/<int:pk>/close/", api_views.close_complaint_api, name="api_close_complaint"),
    path("api/complaints/<int:pk>/feedback/", api_views.feedback_api, name="api_feedback"),
    path("api/complaints/<int:pk>/reopen/", api_views.reopen_api, name="api_reopen"),
    path("api/map-data/", api_views.map_data_api, name="api_map_data"),
    path("api/analytics/", api_views.analytics_api, name="api_analytics"),
    path("api/categories/", api_views.categories_list_api, name="api_categories"),
]
