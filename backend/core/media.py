"""Picture addresses for the apps: ONE place that turns a stored image into thumb / medium / tiny / full addresses.

What MasterProduct.image can hold:
  - "catalog/pack_ab12cd34.png"  an upload made through the admin (Cloudinary in production, a local file in development);
                                 its Cloudinary public ID is the name without the extension (core/storage.py).
  - "690225305747"               an image uploaded straight to Cloudinary whose public ID is the barcode (attached by the
                                 catalogue import or the image sync). No "/" - uploads always sit under "catalog/".
Only the public ID is stored, never a full address, so sizes and the cloud can change later.
Cloudinary transformations make every size from the one upload (no extra uploads):
  thumb  w_300,c_limit,q_auto,f_auto   lists, search, cart
  medium w_800,c_limit,q_auto,f_auto   product detail
  tiny   w_120,c_limit,q_auto,f_auto   order lines
  full   w_1600,c_limit,q_auto,f_auto  tap to open
The cloud name is not a secret; it comes from CLOUDINARY_CLOUD_NAME or from the cloud part of CLOUDINARY_URL.
The API key and secret are never read or written here.
"""
import os
from urllib.parse import quote

from django.conf import settings

SIZES = {"tiny": 120, "thumb": 300, "medium": 800, "full": 1600}


def cloud_name():
    name = getattr(settings, "CLOUDINARY_CLOUD_NAME", "") or ""
    if name:
        return name
    raw = os.environ.get("CLOUDINARY_URL", "")       # cloudinary://<key>:<secret>@<cloud>  - only the cloud is used
    return raw.rsplit("@", 1)[-1].split("/")[0].split("?")[0] if raw.startswith("cloudinary://") and "@" in raw else ""


def _name(field_file):
    return (getattr(field_file, "name", None) or (field_file if isinstance(field_file, str) else "") or "").replace("\\", "/")


def is_cloud_id(name):
    """A public ID attached straight from Cloudinary (a barcode), not a file uploaded through the admin."""
    return bool(name) and "/" not in name


def _uses_cloudinary_storage(field_file):
    return hasattr(getattr(field_file, "storage", None), "thumbnail_url")


def public_id_of(name):
    return os.path.splitext(name)[0] if not is_cloud_id(name) else name


def cloudinary_url(public_id, size="thumb"):
    """https://res.cloudinary.com/<cloud>/image/upload/w_300,c_limit,q_auto,f_auto/<public id>, or None without a cloud."""
    cloud = cloud_name()
    if not cloud or not public_id:
        return None
    return (f"https://res.cloudinary.com/{cloud}/image/upload/w_{SIZES[size]},c_limit,q_auto,f_auto/"
            f"{quote(public_id, safe='/')}")


def image_url(field_file, size="thumb", request=None):
    """The address of this image at this size, or None when there is no image (or it cannot be addressed)."""
    name = _name(field_file)
    if not name:
        return None
    if is_cloud_id(name) or _uses_cloudinary_storage(field_file):
        return cloudinary_url(public_id_of(name), size)
    url = field_file.url                      # a local file in development: there is only one size
    return request.build_absolute_uri(url) if request is not None else url


def image_fields(field_file, request=None):
    """The new fields every product serializer returns."""
    return {"image_thumb": image_url(field_file, "thumb", request),
            "image_medium": image_url(field_file, "medium", request),
            "image_tiny": image_url(field_file, "tiny", request)}


# ---- older helpers, kept so the fields already-installed apps read keep working ("" when there is no image) ----
def full_url(field_file, request=None):
    """The picture at a sensible full size."""
    return image_url(field_file, "full", request) or ""


def thumb_url(field_file, request=None, size=None):
    """A small copy for lists."""
    return image_url(field_file, "thumb", request) or ""
