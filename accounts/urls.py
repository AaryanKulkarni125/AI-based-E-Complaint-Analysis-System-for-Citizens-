from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("login/otp/", views.otp_login_request, name="otp_request"),
    path("login/otp/verify/", views.otp_login_verify, name="otp_verify"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_choice, name="register_choice"),
    path("register/<slug:role>/", views.register, name="register"),
    path("profile/", views.profile_view, name="profile"),
    path("password/change/", views.password_change_view, name="password_change"),
    path("password/reset/", views.password_reset_request_view, name="password_reset"),
]
