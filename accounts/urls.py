from django.urls import path

from . import views

app_name = "accounts"


urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_choice, name="register_choice"),
    path("register/<slug:role>/", views.register, name="register"),
]
