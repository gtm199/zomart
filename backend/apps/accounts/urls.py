from django.urls import path

from .views import LoginView, LogoutView, MeView, RegisterVendorView

urlpatterns = [
    path("register-vendor/", RegisterVendorView.as_view()),
    path("login/", LoginView.as_view()),
    path("logout/", LogoutView.as_view()),
    path("me/", MeView.as_view()),
]
