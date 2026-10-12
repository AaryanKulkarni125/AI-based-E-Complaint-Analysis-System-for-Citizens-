from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/health/", views.health, name="health"),
    path("accounts/", include("accounts.urls")),
    path("complaints/", include("complaints.urls")),
    path("django-admin/", admin.site.urls),
]
# Uploaded attachments are deliberately NOT exposed under MEDIA_URL; they are
# streamed by complaints.views.download_attachment after an access check.
