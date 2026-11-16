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

from .models import ArchivedBill, BillArchive, DataArchive, RetentionLog, RetentionNotice
from .serializers import (ArchiveSerializer, DataArchiveSerializer, LogSerializer, NoticeSerializer,
                          PolicySerializer)

N = RetentionNotice.Status


def _owner_only(request):
    if request.membership.role != "owner":
        raise PermissionDenied("Only the shop owner can change data retention.")


def _mask(email):
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


def _send_zip(shop, subject, body, records, head="bill"):
    if not retention_service.owner_email(shop):
        raise BusinessRuleError("Add your email in Menu > My account first, so the records can be sent to you.", "no_email")
    zipped = retention_service.csv_zip_bytes(records, head)
    name = {"bill": "bills", "order": "orders", "entry": "entries"}.get(head, head + "s")
    if not retention_service.email_owner(shop, subject, body, [(f"{name}.zip", zipped, "application/zip")]):
        raise BusinessRuleError("The email could not be sent. Please try again later.", "email_failed")
    return Response({"sent": True, "to": _mask(retention_service.owner_email(shop)), "bills": len(records)})


class PolicyView(APIView):
    permission_classes = [IsAuthenticated, ShopAccess]
    required_caps = {"get": Cap.MANAGE_SHOP, "patch": Cap.MANAGE_SHOP}

    def _data(self, shop):
        policy = retention_service.policy_for(shop)
        data = PolicySerializer(policy).data
        bills_min = retention_service.min_keep_months(shop)
        data["keep_months"] = retention_service.keep_months_of(policy)   # never shows less than the minimum
        data["minimum_months"] = bills_min
        data["gst_records"] = bills_min > retention_service.MIN_KEEP_MONTHS
        if data["gst_records"]:
            data["gst_note"] = (f"GST shop: bills, tax invoices and credit notes are kept for at least {bills_min} months "
                                "(please confirm the period with your CA). Credit notes are never removed.")
        else:
            data["bills_note"] = ("Item lines of bills older than your setting are moved to the archive (you can email them "
                                  "to yourself). Bill numbers, dates, totals and payments always stay. Reports by product "
                                  "and profit only count bills whose items are still here. Ask your CA how long your "
                                  "business must keep its records.")
        data["minimums"] = {"bills_months": bills_min, "audit_months": retention_service.MIN_AUDIT_MONTHS,
                            "orders_months": retention_service.MIN_ORDER_MONTHS, "notification_days": retention_service.MIN_NOTIFICATION_DAYS}
        data["audit_available"] = retention_service.PLANS["audit"].available()
        data["preview"] = retention_service.preview(shop)
        data["archived_bills"] = ArchivedBill.objects.filter(sale__shop=shop).count()
        data["archived_orders"] = sum(DataArchive.objects.filter(shop=shop, category="orders").values_list("rows_count", flat=True))
        return data

    def get(self, request):
        return Response(self._data(request.shop))

    def patch(self, request):
        _owner_only(request)
        policy = retention_service.policy_for(request.shop)
        s = PolicySerializer(policy, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        bills_min = retention_service.min_keep_months(request.shop)
        if s.validated_data.get("keep_months", bills_min) < bills_min:
            raise BusinessRuleError(f"This shop keeps bill details for at least {bills_min} months "
                                    "(GST records). Choose a longer period.", "below_gst_minimum")
        s.save()
        if not policy.enabled:   # switching it off cancels every warning that is waiting
            RetentionNotice.objects.filter(shop=request.shop, status__in=[N.ANNOUNCED, N.POSTPONED]).update(status=N.CANCELLED)
        else:                    # switching one kind of cleanup off cancels its own warning
            for category, flag in (("bills", policy.clean_bills), ("orders", policy.clean_orders), ("audit", policy.clean_audit)):
                if not flag:
                    RetentionNotice.objects.filter(shop=request.shop, category=category, status__in=[N.ANNOUNCED, N.POSTPONED]).update(status=N.CANCELLED)
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
        """Email the owner everything this warning covers, as a spreadsheet, before anything is archived."""
        _owner_only(request)
        notice = self.get_object()
        records, head = retention_service.records_of_notice(notice)
        return _send_zip(request.shop, f"{request.shop.name}: {notice.category} covered by the retention warning",
                         "The attached spreadsheet has one row per line, with the totals of each record.", records, head)


class LogViewSet(ShopScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = RetentionLog.objects.all()
    serializer_class = LogSerializer
    required_caps = {"*": Cap.MANAGE_SHOP}


class ArchiveViewSet(ShopScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Archived bills."""
    queryset = BillArchive.objects.all()
    serializer_class = ArchiveSerializer
    required_caps = {"*": Cap.MANAGE_SHOP}

    @action(detail=True, methods=["post"])
    def email(self, request, pk=None):
        _owner_only(request)
        archive = self.get_object()
        return _send_zip(request.shop, f"{request.shop.name}: archived bills {archive.period_from} to {archive.period_to}",
                         "The attached spreadsheet has one row per bill item, with each bill's totals and payments.",
                         retention_service.from_archive(archive), "bill")


class DataArchiveViewSet(ShopScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Archived online orders and change-history entries."""
    queryset = DataArchive.objects.all()
    serializer_class = DataArchiveSerializer
    required_caps = {"*": Cap.MANAGE_SHOP}

    @action(detail=True, methods=["post"])
    def email(self, request, pk=None):
        _owner_only(request)
        archive = self.get_object()
        plan = retention_service.PLANS[archive.category]
        records = [plan.csv_shape(r) for r in retention_service.from_data_archive(archive)]
        return _send_zip(request.shop, f"{request.shop.name}: archived {archive.category} {archive.period_from} to {archive.period_to}",
                         "The attached spreadsheet has one row per line, with the totals of each record.", records, plan.head)


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