"""Sync images from Cloudinary: attach images that are on Cloudinary to products that are already in the catalogue.

One service for the admin dashboard button (chunked endpoint) and the `sync_cloudinary_images` command.
  - Only existing products get images; nothing is created from images and nothing is ever deleted.
  - Each barcode of a product is tried, the primary first; the first one that exists on Cloudinary wins.
    Checks are plain HEAD requests (services/cloudinary_image_service.py) - never the Cloudinary Admin API.
  - "could not verify" (timeout, 5xx...) leaves the product unchanged and is counted on its own, so Sync can run again.
  - Chunked and resumable: products are taken in id order, up to `batch` per call; the run remembers the last product
    done. Starting Sync again with the same options continues that run - nothing is checked or attached twice.
  - Dry run (Preview) counts what WOULD be attached and changes no product.
  - Every attached image is written to the product change history ("attached by image sync, run #N").
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import ImageSyncRun, MasterProduct, ProductChangeLog
from services import cloudinary_image_service as cis
from services.exceptions import BusinessRuleError

BATCH = 50
MAX_BATCH = 200
MAX_MISSING_LISTED = 5000


def _products(run):
    qs = MasterProduct.objects.filter(merged_into__isnull=True)
    if not run.replace:
        qs = qs.filter(image="")
    if run.category_id:
        qs = qs.filter(Q(category_id=run.category_id) | Q(category__parent_id=run.category_id))
    if run.brand_id:
        qs = qs.filter(brand_id=run.brand_id)
    return qs.order_by("id")


def report(run):
    remaining = 0 if run.status == ImageSyncRun.Status.FINISHED else _products(run).filter(id__gt=run.last_product_id).count()
    return {"run": run.pk, "dry_run": run.dry_run, "replace": run.replace, "status": run.status,
            "total": run.total, "processed": run.processed, "attached": run.attached,
            "still_missing": run.still_missing, "unverified": run.unverified, "skipped": run.skipped,
            "remaining": remaining, "finished": run.status == ImageSyncRun.Status.FINISHED}


def start(user=None, dry_run=False, replace=False, category=None, brand=None):
    """A new run - or the unfinished run with exactly these options, which then simply continues."""
    if not cis.cloud_name():
        raise BusinessRuleError("Set CLOUDINARY_CLOUD_NAME (or CLOUDINARY_URL) first.", "cloudinary_not_configured")
    same = ImageSyncRun.objects.filter(status=ImageSyncRun.Status.RUNNING, dry_run=dry_run, replace=replace,
                                       category=category, brand=brand).order_by("-id").first()
    if same is not None:
        return same
    run = ImageSyncRun(started_by=user if getattr(user, "pk", None) else None, dry_run=dry_run, replace=replace,
                       category=category, brand=brand)
    run.total = _products(run).count()
    run.save()
    return run


def _candidates(product):
    """The product's barcodes, primary first."""
    return [b.code for b in sorted(product.barcodes.all(), key=lambda b: (not b.is_primary, b.id))]


def _find_images(products):
    """{product_id: ("found", public_id) | ("missing", None) | ("unverified", None) | ("no_barcode", None)}.
    Checks in rounds - all first barcodes together, then second barcodes for those still without an image..."""
    codes = {p.pk: _candidates(p) for p in products}
    out, unsure = {}, set()
    for pid, cs in codes.items():
        if not cs:
            out[pid] = ("no_barcode", None)
    depth = 0
    while True:
        asking = {pid: cs[depth] for pid, cs in codes.items() if pid not in out and depth < len(cs)}
        if not asking:
            break
        answers = cis.check_many(asking.values())
        for pid, code in asking.items():
            status = answers.get(code, cis.UNVERIFIED)
            if status == cis.FOUND:
                out[pid] = (cis.FOUND, code)        # first barcode that exists wins
            elif status == cis.UNVERIFIED:
                unsure.add(pid)
        depth += 1
    for pid in codes:
        if pid not in out:
            out[pid] = (cis.UNVERIFIED, None) if pid in unsure else (cis.MISSING, None)
    return out


def step(run_id, user=None, batch=BATCH):
    """Processes the next `batch` products of this run and returns the totals so far (with `remaining`)."""
    batch = max(1, min(int(batch or BATCH), MAX_BATCH))
    run = ImageSyncRun.objects.filter(pk=run_id).first()
    if run is None:
        raise BusinessRuleError("Sync run not found.", "sync_run_not_found", 404)
    if run.status != ImageSyncRun.Status.RUNNING:
        return report(run)
    cursor = run.last_product_id
    products = list(_products(run).filter(id__gt=cursor).prefetch_related("barcodes")[:batch])
    if not products:
        ImageSyncRun.objects.filter(pk=run.pk, last_product_id=cursor).update(
            status=ImageSyncRun.Status.FINISHED, finished_at=timezone.now())
        run.refresh_from_db()
        return report(run)
    found = _find_images(products)        # network: outside any database lock
    with transaction.atomic():
        run = ImageSyncRun.objects.select_for_update().get(pk=run.pk)
        if run.last_product_id != cursor or run.status != ImageSyncRun.Status.RUNNING:
            return report(run)            # another call already did this chunk: nothing twice
        missing = list(run.missing_barcodes or [])
        for p in products:
            status, public_id = found[p.pk]
            run.processed += 1
            if status == "no_barcode":
                run.skipped += 1
            elif status == cis.UNVERIFIED:
                run.unverified += 1       # left unchanged; Sync can run again
            elif status == cis.MISSING:
                run.still_missing += 1
                if len(missing) < MAX_MISSING_LISTED:
                    missing.append(_candidates(p)[0])
            else:
                current = MasterProduct.objects.select_for_update().only("image").get(pk=p.pk)
                if current.image.name == public_id or (current.image and not run.replace):
                    run.skipped += 1      # already this image, or one was added meanwhile and replace is off
                elif run.dry_run:
                    run.attached += 1     # would be attached
                else:
                    old = current.image.name
                    MasterProduct.objects.filter(pk=p.pk).update(image=public_id, updated_at=timezone.now())
                    ProductChangeLog.objects.create(
                        product_id=p.pk, changed_by=user if getattr(user, "pk", None) else run.started_by,
                        field="image", old_value=old, new_value=f"{public_id} (attached by image sync, run #{run.pk})")
                    run.attached += 1
        run.missing_barcodes = missing
        run.last_product_id = products[-1].pk
        if not _products(run).filter(id__gt=run.last_product_id).exists():
            run.status, run.finished_at = ImageSyncRun.Status.FINISHED, timezone.now()
        run.save()
    return report(run)


def run_all(user=None, dry_run=False, replace=False, category=None, brand=None, limit=None, batch=BATCH, progress=None):
    """Runs Sync to the end (or `limit` products) - for the command line."""
    run = start(user, dry_run, replace, category, brand)
    r = report(run)
    while not r["finished"]:
        if limit is not None and r["processed"] >= limit:
            break
        size = batch if limit is None else max(1, min(batch, limit - r["processed"]))
        r = step(run.pk, user, size)
        if progress:
            progress(r)
    return r


RECHECK_MAX = 100          # products per "re-check image" action
RECHECK_PER_HOUR = 1000    # products per staff member per hour (HEAD requests, not the Admin API)


def recheck_allowance(user, wanted):
    """Simple per-person rate limit for "re-check image". Returns how many may be checked now."""
    from django.core.cache import cache
    key = f"image_recheck:{getattr(user, 'pk', 0)}"
    used = cache.get(key, 0)
    allowed = max(0, min(wanted, RECHECK_MAX, RECHECK_PER_HOUR - used))
    if allowed:
        cache.set(key, used + allowed, 3600)
    return allowed


def recheck_many(products, user=None):
    """Looks for these products' images again (admin "re-check image"), in parallel. Attaches only to products that
    have no image; never removes or overwrites one. Returns {"attached", "already", "kept", "missing", "unverified",
    "no_barcode"} counts."""
    counts = dict.fromkeys(("attached", "already", "kept", "missing", "unverified", "no_barcode"), 0)
    products = list(MasterProduct.objects.filter(pk__in=[p.pk for p in products]).prefetch_related("barcodes"))
    found = _find_images(products)
    for p in products:
        status, public_id = found[p.pk]
        if status != cis.FOUND:
            counts[status] += 1
            continue
        with transaction.atomic():
            current = MasterProduct.objects.select_for_update().only("image").get(pk=p.pk)
            if current.image.name == public_id:
                counts["already"] += 1
            elif current.image:
                counts["kept"] += 1        # has another image: re-check never overwrites
            else:
                MasterProduct.objects.filter(pk=p.pk).update(image=public_id, updated_at=timezone.now())
                ProductChangeLog.objects.create(product_id=p.pk, changed_by=user if getattr(user, "pk", None) else None,
                                                field="image", old_value="", new_value=f"{public_id} (attached by re-check)")
                counts["attached"] += 1
    return counts


def recheck(product, user=None):
    """One product: "attached", "already", "kept", "missing", "unverified" or "no_barcode"."""
    counts = recheck_many([product], user)
    return next(k for k, v in counts.items() if v)
