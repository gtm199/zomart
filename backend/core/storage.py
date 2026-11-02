import os
import urllib.request
import uuid

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class CloudinaryMediaStorage(Storage):
    """Keeps uploaded images on Cloudinary. The database stores only a short name such as 'catalog/pack_ab12cd34.png'.
    Credentials come from the CLOUDINARY_URL environment variable (the Cloudinary library reads it by itself)."""

    FULL_MAX = 1600  # the largest side of the "full size" picture

    @staticmethod
    def _public_id(name):
        return os.path.splitext(name.replace("\\", "/"))[0]

    def get_available_name(self, name, max_length=None):
        """A new random ending for every upload, so names never clash and we never need to ask Cloudinary."""
        root, ext = os.path.splitext(name.replace("\\", "/"))
        suffix = f"_{uuid.uuid4().hex[:8]}{ext.lower()}"
        if max_length and len(root) + len(suffix) > max_length:
            root = root[: max_length - len(suffix)]
        return f"{root}{suffix}"

    def exists(self, name):
        return False

    def _save(self, name, content):
        content.seek(0)
        cloudinary.uploader.upload(
            content, public_id=self._public_id(name), resource_type="image", overwrite=False,
            unique_filename=False, use_filename=False)
        return name.replace("\\", "/")

    def delete(self, name):
        try:
            cloudinary.uploader.destroy(self._public_id(name), resource_type="image", invalidate=True)
        except Exception:
            pass  # a missing picture must never break saving or deleting a product

    def _build(self, name, **options):
        url, _ = cloudinary.utils.cloudinary_url(
            self._public_id(name), secure=True, resource_type="image", type="upload",
            fetch_format="auto", quality="auto", **options)
        return url

    def url(self, name):
        return self._build(name, width=self.FULL_MAX, height=self.FULL_MAX, crop="limit")

    def thumbnail_url(self, name, size=400):
        return self._build(name, width=size, height=size, crop="limit")

    def size(self, name):
        return 0  # not needed by the apps

    def _open(self, name, mode="rb"):
        with urllib.request.urlopen(self.url(name), timeout=20) as response:
            return ContentFile(response.read(), name=name)