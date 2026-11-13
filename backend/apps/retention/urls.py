from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("shop/retention/notices", views.NoticeViewSet, basename="retention-notice")
router.register("shop/retention/log", views.LogViewSet, basename="retention-log")
router.register("shop/retention/archives", views.ArchiveViewSet, basename="retention-archive")

urlpatterns = [
    path("shop/retention/policy/", views.PolicyView.as_view()),
    path("internal/retention/run/", views.RunRetentionView.as_view()),
] + router.urls