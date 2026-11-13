import hmac
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.shops.roles import Cap
from core.tenancy import ShopAccess, ShopScopedMixin
from services import retention_service
from services.exceptions import BusinessRuleError

from .models import ArchivedBill, BillArchive, RetentionLog, RetentionNotice
from .serializers import ArchiveSerializer, LogSerializer, NoticeSerializer, PolicySerializer

N = RetentionNotice.Status


def _owner_only(request):
    if request.membership.role != "owner":
        raise PermissionDenied("Only the shop owner can change data retention.")


def _mask(email):
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


def _send_zip(shop, subject, body, bills):
    if not retention_service.owner_email(shop):
        raise BusinessRuleError("Add your email in Menu > My account first, so the bills can be sent to you.", "no_email")
    zipped = retention_service.csv_zip_bytes(bills)
    if not retention_service.email_owner(shop, subject, body, [("bills.zip", zipped, "application/zip")]):
        raise BusinessRuleError("The email could not be sent. Please try again later.", "email_failed")
    return Response({"sent": True, "to": _mask(retention_service.owner_email(shop)), "bills": len(bills)})


class PolicyView(APIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.MANAGE_SHOP, "patch": Cap.MANAGE_SHOP}

    def _data(self, shop):
        policy = retention_service.policy_for(shop)
        data = PolicySerializer(policy).data
        data["minimum_months"] = retention_service.MIN_KEEP_MONTHS
        data["preview"] = retention_service.preview(shop)
        data["archived_bills"] = ArchivedBill.objects.filter(archive__shop=shop).count()
        return data

    def get(self, request):
        return Response(self._data(request.shop))

    def patch(self, request):
        _owner_only(request)
        policy = retention_service.policy_for(request.shop)
        s = PolicySerializer(policy, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        if not policy.enabled:   # switching it off cancels any warning that is waiting
            RetentionNotice.objects.filter(shop=request.shop, status__in=[N.ANNOUNCED, N.POSTPONED]).update(status=N.CANCELLED)
        return Response(self._data(request.shop))


class NoticeViewSet(ShopScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = RetentionNotice.objects.all()
    serializer_class = NoticeSerializer
    required_caps = {"*": Cap.MANAGE_SHOP}

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("status"):
            qs = qs.filter(status__in=self.request.query_params["status"].split(","))
        return qs

    @action(detail=True, methods=["post"])
    def postpone(self, request, pk=None):
        _owner_only(request)
        notice = self.get_object()
        if notice.status not in (N.ANNOUNCED, N.POSTPONED):
            raise BusinessRuleError("This warning is finished.", "wrong_status")
        if notice.postponed_count >= retention_service.MAX_POSTPONES:
            raise BusinessRuleError(f"A warning can be postponed {retention_service.MAX_POSTPONES} times at most.", "too_many_postponements")
        notice.delete_after = max(notice.delete_after, timezone.localdate()) + timedelta(days=30)
        notice.status = N.POSTPONED
        notice.postponed_count += 1
        notice.save(update_fields=["delete_after", "status", "postponed_count"])
        return Response(NoticeSerializer(notice).data)

    @action(detail=True, methods=["post"], url_path="email-export")
    def email_export(self, request, pk=None):
        """Email the owner every bill covered by this warning, as a spreadsheet, before anything is archived."""
        _owner_only(request)
        notice = self.get_object()
        bills = retention_service.bills_of_notice(notice)
        return _send_zip(request.shop, f"{request.shop.name}: bills covered by the retention warning",
                         "The attached spreadsheet has one row per bill item, with each bill's totals and payments.", bills)


class LogViewSet(ShopScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = RetentionLog.objects.all()
    serializer_class = LogSerializer
    required_caps = {"*": Cap.MANAGE_SHOP}


class ArchiveViewSet(ShopScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = BillArchive.objects.all()
    serializer_class = ArchiveSerializer
    required_caps = {"*": Cap.MANAGE_SHOP}

    @action(detail=True, methods=["post"])
    def email(self, request, pk=None):
        """Email the owner an archived set of bills as a spreadsheet."""
        _owner_only(request)
        archive = self.get_object()
        return _send_zip(request.shop, f"{request.shop.name}: archived bills {archive.period_from} to {archive.period_to}",
                         "The attached spreadsheet has one row per bill item, with each bill's totals and payments.",
                         retention_service.from_archive(archive))


class RunRetentionView(APIView):
    """Called once a day by a scheduler (see the setup steps). The token must match RETENTION_CRON_TOKEN."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        token = getattr(settings, "RETENTION_CRON_TOKEN", "")
        if not token or not hmac.compare_digest(request.headers.get("X-Cron-Token", ""), token):
            return Response({"detail": "Not found."}, status=404)   # looks like no such page to anyone without the token
        return Response({"results": retention_service.run_all()})