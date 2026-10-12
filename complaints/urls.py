from django.urls import path

from . import views

app_name = "complaints"


urlpatterns = [
    path("submit/", views.submit, name="submit"),
    path("mine/", views.my_list, name="my_list"),
    path("assigned/", views.officer_list, name="officer_list"),
    path("<int:pk>/", views.detail, name="detail"),
    path("attachments/<int:pk>/", views.download_attachment, name="attachment"),
]
