from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from core.media import image_url, thumb_url

from services import barcode_service, catalog_import_service, catalog_service, export_service, image_sync_service
from services.exceptions import BusinessRuleError

from .models import Brand, Category, ImageSyncRun, MasterProduct, ProductBarcode, ProductChangeLog, ProductSuggestion

S = MasterProduct.Status

# ---------------- barcodes: validation and clear conflict messages ----------------
class BarcodeForm(forms.ModelForm):
    class Meta:
        model = ProductBarcode
        fields = ["code", "symbology", "is_primary"]

    def clean_code(self):
        try:
            code = barcode_service.validate_barcode(self.cleaned_data["code"])[0]
        except ValueError as exc:
            raise forms.ValidationError(str(exc))
        other = ProductBarcode.objects.filter(code=code).exclude(pk=self.instance.pk).select_related("product").first()
        if other:
            raise forms.ValidationError(f"Barcode conflict: already on product #{other.product_id} ({other.product}).")
        return code


class BarcodeInline(admin.TabularInline):
    model = ProductBarcode
    form = BarcodeForm
    extra = 1


# ---------------- filters ----------------
class ImageFilter(admin.SimpleListFilter):
    title = "image"
    parameter_name = "image"

    def lookups(self, request, model_admin):
        return [("missing", "No image"), ("has", "Has image")]

    def queryset(self, request, qs):
        if self.value() == "missing":
            return qs.filter(image="")
        if self.value() == "has":
            return qs.exclude(image="")
        return qs


class VerifiedFilter(admin.SimpleListFilter):
    title = "MRP / GST check"
    parameter_name = "verified"

    def lookups(self, request, model_admin):
        return [("no_mrp", "No MRP set"), ("unverified", "MRP not verified"), ("verified", "MRP verified")]

    def queryset(self, request, qs):
        if self.value() == "no_mrp":
            return qs.filter(mrp__isnull=True)
        if self.value() == "unverified":
            return qs.filter(mrp__isnull=False, mrp_verified_at__isnull=True)
        if self.value() == "verified":
            return qs.filter(mrp_verified_at__isnull=False)
        return qs


# ---------------- products ----------------
@admin.register(MasterProduct)
class MasterProductAdmin(admin.ModelAdmin):
    change_list_template = "admin/catalog/masterproduct/change_list.html"
    change_form_template = "admin/catalog/masterproduct/change_form.html"
    list_display = ("thumb", "name", "brand", "pack_size", "unit", "category", "status", "mrp", "verified", "shops")
    list_filter = ("status", ImageFilter, VerifiedFilter, "category", "brand")
    search_fields = ("name", "brand__name", "barcodes__code", "search_keywords")
    inlines = [BarcodeInline]
    readonly_fields = ("image_preview", "mrp_verified_by", "mrp_verified_at", "merged_into")
    actions = ["submit_for_review", "make_active", "make_inactive", "mark_verified", "recheck_images",
               "export_csv", "export_xlsx"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(shop_total=Count("shopproduct", distinct=True))

    @admin.display(description="Image")
    def thumb(self, obj):
        return format_html('<img src="{}" style="height:36px;border-radius:4px">', thumb_url(obj.image)) if obj.image else "-"

    @admin.display(description="Current image")
    def image_preview(self, obj):
        return format_html('<img src="{}" style="max-height:160px">', image_url(obj.image, "medium")) if obj and obj.image else "No image yet"

    @admin.display(boolean=True, description="MRP verified")
    def verified(self, obj):
        return bool(obj.mrp_verified_at)

    @admin.display(ordering="shop_total", description="Shops")
    def shops(self, obj):
        return obj.shop_total

    # ---- editors cannot make products live ----
    def save_model(self, request, obj, form, change):
        before, old_status = None, S.DRAFT
        if change:
            old = MasterProduct.objects.get(pk=obj.pk)
            before, old_status = catalog_service.snapshot(old), old.status
        else:
            obj.created_by = request.user
        try:
            catalog_service.ensure_can_set_status(request.user, old_status, obj.status)
        except BusinessRuleError as exc:
            obj.status = old_status
            self.message_user(request, exc.message + " The status was not changed.", messages.WARNING)
        super().save_model(request, obj, form, change)
        if before:
            catalog_service.log_changes(obj, before, request.user)

    def _set_status(self, request, queryset, new_status, only_from=None):
        done = 0
        for p in queryset:
            if only_from and p.status not in only_from:
                continue
            try:
                catalog_service.ensure_can_set_status(request.user, p.status, new_status)
            except BusinessRuleError as exc:
                self.message_user(request, exc.message, messages.ERROR)
                return
            before = catalog_service.snapshot(p)
            p.status = new_status
            p.save(update_fields=["status", "updated_at"])
            catalog_service.log_changes(p, before, request.user)
            done += 1
        self.message_user(request, f"{done} product(s) updated.")

    @admin.action(description="Submit for review (editors)")
    def submit_for_review(self, request, queryset):
        self._set_status(request, queryset, S.PENDING, only_from=[S.DRAFT])

    @admin.action(description="Make ACTIVE (approvers only)")
    def make_active(self, request, queryset):
        self._set_status(request, queryset, S.ACTIVE)

    @admin.action(description="Make INACTIVE and notify shops (approvers only)")
    def make_inactive(self, request, queryset):
        self._set_status(request, queryset, S.INACTIVE)

    @admin.action(description="Mark MRP and GST as verified (checked on the pack)")
    def mark_verified(self, request, queryset):
        done = 0
        for p in queryset:
            try:
                catalog_service.mark_verified(p, request.user, "pack")
                done += 1
            except BusinessRuleError as exc:
                self.message_user(request, f"{p.display_name}: {exc.message}", messages.WARNING)
        self.message_user(request, f"{done} product(s) marked verified.")

    # ---- images from Cloudinary (HEAD checks only, never the Admin API) ----
    def _recheck(self, request, products):
        if not request.user.has_perm("catalog.change_masterproduct"):
            self.message_user(request, "You cannot change catalogue products.", messages.ERROR)
            return
        allowed = image_sync_service.recheck_allowance(request.user, len(products))
        if allowed == 0:
            self.message_user(request, "Re-check limit reached for this hour. Try again later, or use Sync on the "
                                       "dashboard.", messages.WARNING)
            return
        c = image_sync_service.recheck_many(products[:allowed], request.user)
        self.message_user(request, (
            f"Re-checked {allowed} product(s): {c['attached']} image(s) attached, {c['missing']} not on Cloudinary, "
            f"{c['unverified']} could not be verified (unchanged), {c['already'] + c['kept']} already had an image, "
            f"{c['no_barcode']} without barcode."), messages.SUCCESS if c["attached"] else messages.INFO)
        if allowed < len(products):
            self.message_user(request, f"Only the first {allowed} were checked (at most "
                                       f"{image_sync_service.RECHECK_MAX} at a time). Use Sync for large sets.",
                              messages.WARNING)

    @admin.action(description="Re-check image on Cloudinary (attach if found, never overwrite)")
    def recheck_images(self, request, queryset):
        self._recheck(request, list(queryset.order_by("id")[:image_sync_service.RECHECK_MAX + 1]))

    def recheck_one_view(self, request, object_id):
        if request.method != "POST":
            return redirect("admin:catalog_masterproduct_change", object_id)
        product = MasterProduct.objects.filter(pk=object_id).first()
        if product is not None:
            self._recheck(request, [product])
        return redirect("admin:catalog_masterproduct_change", object_id)

    @admin.action(description="Export selected to CSV")
    def export_csv(self, request, queryset):
        header, rows = catalog_import_service.export_rows(queryset)
        return export_service.csv_response("catalogue.csv", header, rows)

    @admin.action(description="Export selected to Excel (XLSX)")
    def export_xlsx(self, request, queryset):
        header, rows = catalog_import_service.export_rows(queryset)
        try:
            return export_service.xlsx_response("catalogue.xlsx", header, rows)
        except ImportError:
            self.message_user(request, "Excel export needs the openpyxl package: pip install openpyxl", messages.ERROR)

    # ---- two extra pages: dashboard and import with preview ----
    def get_urls(self):
        extra = [
            path("dashboard/", self.admin_site.admin_view(self.dashboard_view), name="catalog_dashboard"),
            path("import/", self.admin_site.admin_view(self.import_view), name="catalog_import"),
            path("<path:object_id>/recheck-image/", self.admin_site.admin_view(self.recheck_one_view),
                 name="catalog_recheck_image"),
        ]
        return extra + super().get_urls()

    def dashboard_view(self, request):
        base = MasterProduct.objects.all()
        active = base.filter(status=S.ACTIVE)
        cl = reverse("admin:catalog_masterproduct_changelist")
        sug = reverse("admin:catalog_productsuggestion_changelist")
        stats = [
            ("Active (visible to shops)", active.count(), f"{cl}?status__exact=active", ""),
            ("Waiting for review", base.filter(status=S.PENDING).count(), f"{cl}?status__exact=pending_review", "An approver must decide"),
            ("Draft", base.filter(status=S.DRAFT).count(), f"{cl}?status__exact=draft", "Not visible to shops"),
            ("Inactive", base.filter(status=S.INACTIVE).count(), f"{cl}?status__exact=inactive", ""),
            ("Active, no image", active.filter(image="").count(), f"{cl}?status__exact=active&image=missing", ""),
            ("Active, no MRP", active.filter(mrp__isnull=True).count(), f"{cl}?status__exact=active&verified=no_mrp", ""),
            ("Active, MRP not verified", active.filter(mrp__isnull=False, mrp_verified_at__isnull=True).count(),
             f"{cl}?status__exact=active&verified=unverified", "Check on the pack, then verify"),
            ("Active, no barcode (not loose)", active.filter(is_loose=False, barcodes__isnull=True).count(), cl, "Cannot be scanned"),
            ("Active, used by no shop", active.annotate(n=Count("shopproduct")).filter(n=0).count(), cl, ""),
            ("Vendor suggestions waiting", ProductSuggestion.objects.filter(status="pending").count(),
             f"{sug}?status__exact=pending", ""),
        ]
        top = MasterProduct.objects.annotate(n=Count("shopproduct", distinct=True)).filter(n__gt=0).order_by("-n")[:15]
        no_image = base.filter(image="", merged_into__isnull=True)
        ctx = dict(self.admin_site.each_context(request), title="Catalogue dashboard", stats=stats, top=top,
                   no_image_total=no_image.count(), no_image_url=f"{cl}?image=missing",
                   sync_categories=Category.objects.filter(parent=None).order_by("name"),
                   sync_brands=Brand.objects.order_by("name"),
                   sync_runs=ImageSyncRun.objects.select_related("started_by", "category", "brand")[:10],
                   can_sync=request.user.is_staff and request.user.has_perm("catalog.change_masterproduct"))
        return render(request, "admin/catalog/dashboard.html", ctx)

    def import_view(self, request):
        ctx = dict(self.admin_site.each_context(request), title="Import products (preview first)",
                   can_activate=catalog_service.can_approve(request.user))
        if request.method == "POST" and "commit" in request.POST:
            rows = request.session.pop("catalog_import_rows", None)
            known = request.session.pop("catalog_import_images", None) or {}
            replace = bool(request.session.pop("catalog_import_replace", False))
            if not rows:
                self.message_user(request, "The preview expired. Upload the file again.", messages.ERROR)
                return redirect("admin:catalog_import")
            # check the rows again (data may have changed) but reuse the preview's image answers: equal totals
            p = catalog_import_service.plan(rows, replace_images=replace, known=known)
            activate = bool(request.POST.get("activate")) and ctx["can_activate"]
            r = catalog_import_service.commit_plan(p, activate=activate, user=request.user)
            ctx.update(report=r, missing=p["missing"], errors=p["errors"], activated=activate,
                       title="Import finished")
            return render(request, "admin/catalog/import.html", ctx)
        if request.method == "POST" and request.FILES.get("file"):
            f = request.FILES["file"]
            try:
                if f.name.lower().endswith(".xlsx"):
                    rows = catalog_import_service.read_xlsx(f)
                else:
                    rows = catalog_import_service.read_csv(f.read().decode("utf-8-sig"))
            except ImportError:
                self.message_user(request, "XLSX files need the openpyxl package: pip install openpyxl", messages.ERROR)
                return redirect("admin:catalog_import")
            except Exception as exc:
                self.message_user(request, f"Could not read the file: {exc}", messages.ERROR)
                return redirect("admin:catalog_import")
            replace = bool(request.POST.get("replace_images"))
            p = catalog_import_service.plan(rows, replace_images=replace)
            request.session["catalog_import_rows"] = rows
            request.session["catalog_import_images"] = p["statuses"]
            request.session["catalog_import_replace"] = replace
            ctx.update(previewed=True, good_count=len(p["good"]), errors=p["errors"], sample=p["good"][:20],
                       filename=f.name, totals=p["totals"], missing=p["missing"], large_file=p["large_file"],
                       replace_images=replace, existing=p["existing"])
        return render(request, "admin/catalog/import.html", ctx)


# ---------------- vendor suggestions ----------------
@admin.register(ProductSuggestion)
class ProductSuggestionAdmin(admin.ModelAdmin):
    list_display = ("name", "brand_name", "barcode", "pack_size", "unit", "shop", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "brand_name", "barcode")
    actions = ["approve", "reject"]

    @admin.action(description="Approve: create a DRAFT product from the selected suggestions")
    def approve(self, request, queryset):
        n = 0
        for s in queryset.filter(status=ProductSuggestion.Status.PENDING):
            catalog_service.approve_suggestion(s, request.user)
            n += 1
        self.message_user(request, f"{n} draft product(s) created. Review them under Master products > Draft.")

    @admin.action(description="Reject the selected suggestions")
    def reject(self, request, queryset):
        n = queryset.filter(status=ProductSuggestion.Status.PENDING).update(
            status=ProductSuggestion.Status.REJECTED, reviewed_by=request.user)
        self.message_user(request, f"{n} suggestion(s) rejected.")


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "sort_order")
    search_fields = ("name",)


@admin.register(ProductChangeLog)
class ProductChangeLogAdmin(admin.ModelAdmin):
    list_display = ("changed_at", "product", "field", "old_value", "new_value", "changed_by")
    list_filter = ("field",)
    search_fields = ("product__name",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

# ---------------- image sync run log (read-only) ----------------
@admin.register(ImageSyncRun)
class ImageSyncRunAdmin(admin.ModelAdmin):
    """What "Sync images from Cloudinary" did: who, when, options, totals. Written only by the sync service."""
    list_display = ("id", "started_at", "started_by", "dry_run", "replace", "category", "brand", "status",
                    "processed", "attached", "still_missing", "unverified", "skipped", "missing_csv")
    list_filter = ("status", "dry_run", "replace")
    readonly_fields = [f.name for f in ImageSyncRun._meta.fields] + ["missing_csv"]
    exclude = ("missing_barcodes",)

    @admin.display(description="Still missing")
    def missing_csv(self, obj):
        if not obj.missing_barcodes:
            return "-"
        return format_html('<a href="/api/v1/platform/catalog/image-sync/{}/missing.csv">Download CSV ({})</a>',
                           obj.pk, len(obj.missing_barcodes))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
