"""Platform admin: Sync images from Cloudinary, one chunk per call (works within Render free plan request limits).

POST platform/catalog/image-sync/            {dry_run, replace, category, brand}  -> starts (or continues) a run
POST platform/catalog/image-sync/<id>/step/  {batch}                              -> next chunk; repeat until remaining = 0
GET  platform/catalog/image-sync/            the latest runs (the run log)
GET  platform/catalog/image-sync/<id>/missing.csv   barcodes still without an image
Platform staff with the "change master product" permission only. Signed in with a token or the admin session
(session calls need the CSRF token). Throttled. Never uses the Cloudinary Admin API.
"""
import csv
import io

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.permissions import BasePermission, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from services import image_sync_service

from .models import Brand, Category, ImageSyncRun


class CanEditCatalogue(BasePermission):
    message = "Only catalogue staff can sync images."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_staff and u.has_perm("catalog.change_masterproduct"))


class _Base(APIView):
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAdminUser, CanEditCatalogue]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "image_sync"


class StartSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField(default=False)
    replace = serializers.BooleanField(default=False)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), required=False, allow_null=True)
    brand = serializers.PrimaryKeyRelatedField(queryset=Brand.objects.all(), required=False, allow_null=True)


def run_row(run):
    return {**image_sync_service.report(run), "started_at": run.started_at, "finished_at": run.finished_at,
            "started_by": getattr(run.started_by, "username", ""),
            "category": run.category.name if run.category_id else "", "brand": run.brand.name if run.brand_id else ""}


class ImageSyncView(_Base):
    def get(self, request):
        runs = ImageSyncRun.objects.select_related("started_by", "category", "brand")[:20]
        return Response([run_row(r) for r in runs])

    def post(self, request):
        s = StartSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        run = image_sync_service.start(request.user, **s.validated_data)
        return Response(image_sync_service.report(run))


class ImageSyncStepView(_Base):
    def post(self, request, run_id):
        try:
            batch = int(request.data.get("batch") or image_sync_service.BATCH)
        except (TypeError, ValueError):
            batch = image_sync_service.BATCH
        return Response(image_sync_service.step(run_id, request.user, batch))


class ImageSyncMissingCsvView(_Base):
    throttle_classes = []

    def get(self, request, run_id):
        run = ImageSyncRun.objects.filter(pk=run_id).first()
        if run is None:
            return Response({"detail": "Sync run not found."}, status=404)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["barcode"])
        for code in run.missing_barcodes or []:
            w.writerow([code])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="images_still_missing_run{run.pk}.csv"'
        return resp
