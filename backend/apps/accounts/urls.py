from django.urls import path

from .views import LoginView, LogoutView, MeView, RegisterVendorView, ForgotPasswordView, ResetPasswordView, ProfileView

urlpatterns = [
    path("register-vendor/", RegisterVendorView.as_view()),
    path("login/", LoginView.as_view()),
    path("logout/", LogoutView.as_view()),
    path("me/", MeView.as_view()),
    path("forgot-password/", ForgotPasswordView.as_view()),
    path("reset-password/", ResetPasswordView.as_view()),
    path("profile/", ProfileView.as_view()),
]
