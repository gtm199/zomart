"""Picture addresses for the apps. Works with Cloudinary and with plain local files (development)."""


def full_url(field_file, request=None):
    """The picture at a sensible full size."""
    if not field_file:
        return ""
    url = field_file.url
    return request.build_absolute_uri(url) if request is not None else url


def thumb_url(field_file, request=None, size=400):
    """A small copy for lists. Cloudinary makes it from the same upload; local files have no small copy."""
    if not field_file:
        return ""
    storage = field_file.storage
    if hasattr(storage, "thumbnail_url"):
        return storage.thumbnail_url(field_file.name, size)
    return full_url(field_file, request)