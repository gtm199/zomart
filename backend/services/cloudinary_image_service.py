"""Finding product images on Cloudinary by public ID (= the barcode), without the Admin API.

Each image is checked with a plain HEAD request to its public delivery address
    https://res.cloudinary.com/<cloud>/image/upload/<public id>
which does not count against the Admin API limit (500 calls/hour on the free plan). Only the cloud NAME is used;
the API key/secret are never read, sent or logged here.

Result per public ID:  "found" (200)  |  "missing" (404)  |  "unverified" (anything else: timeout, 5xx, a redirect...)
"unverified" must never delete or overwrite an image - callers leave the product as it is.
Only addresses on OUR cloud are accepted, so an import file can never make the server fetch other sites (SSRF).
"""
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, unquote, urlsplit

from core.media import cloud_name

FOUND, MISSING, UNVERIFIED = "found", "missing", "unverified"
HOST = "res.cloudinary.com"
TIMEOUT = 5            # seconds per request
WORKERS = 8            # parallel requests
TIME_BUDGET = 20       # seconds for one batch; whatever is left is "unverified" (run Sync later)
PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,254}$")    # dynamic folders: no folder in the ID
VERSION = re.compile(r"^v\d+$")
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None          # a redirect is answered as "unverified", never followed


_opener = urllib.request.build_opener(_NoRedirect)


def delivery_url(public_id):
    return f"https://{HOST}/{cloud_name()}/image/upload/{quote(public_id, safe='')}"


def _head(url):
    """HTTP status of a HEAD request (no redirects). Raises OSError for network problems."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "catalogue-image-check"})
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def check_one(public_id):
    if not cloud_name() or not PUBLIC_ID.match(public_id or ""):
        return UNVERIFIED
    url = delivery_url(public_id)
    for attempt in (1, 2):                      # one retry for network errors only
        try:
            code = _head(url)
        except (OSError, ValueError):
            if attempt == 2:
                return UNVERIFIED
            continue
        return FOUND if code == 200 else MISSING if code == 404 else UNVERIFIED
    return UNVERIFIED


def check_many(public_ids, budget=TIME_BUDGET):
    """{public_id: status} for each distinct ID, checked in parallel within the time budget."""
    ids = list(dict.fromkeys(i for i in public_ids if i))
    out = {i: UNVERIFIED for i in ids}
    if not ids:
        return out
    deadline = time.monotonic() + budget
    pool = ThreadPoolExecutor(max_workers=min(WORKERS, len(ids)))
    try:
        futures = {pool.submit(check_one, i): i for i in ids}
        try:
            for f in as_completed(futures, timeout=max(0.1, deadline - time.monotonic())):
                out[futures[f]] = f.result()
        except TimeoutError:
            pass                               # the rest stays "unverified"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out


def parse_image_ref(value):
    """The public ID in the import file's "image" column: a public ID, or a full address on OUR cloud.
    Returns "" for blank. Raises ValueError for another site, another cloud, or a malformed value."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value or value.startswith("//"):
        parts = urlsplit(value if "://" in value else "https:" + value)
        if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() != HOST:
            raise ValueError("image: only addresses on res.cloudinary.com (your own cloud) are accepted")
        segs = [unquote(s) for s in parts.path.split("/") if s]
        cloud = cloud_name()
        if len(segs) < 4 or segs[0] != cloud or segs[1:3] != ["image", "upload"]:
            raise ValueError("image: the address is not an image on your Cloudinary cloud")
        rest = segs[3:]
        while len(rest) > 1 and ("," in rest[0] or "_" in rest[0][:3] or VERSION.match(rest[0])):
            rest = rest[1:]                    # drop transformations (w_300,...) and the version (v1712...)
        if len(rest) != 1:
            raise ValueError("image: use a public ID without folders (your account uses dynamic folders)")
        value = rest[0]
    for ext in EXTENSIONS:
        if value.lower().endswith(ext):
            value = value[: -len(ext)]
            break
    if not PUBLIC_ID.match(value):
        raise ValueError("image: the public ID may use letters, numbers, - _ . only (no folders or spaces)")
    return value


SCIENTIFIC = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")


def clean_barcode_text(raw):
    """Undoes harmless spreadsheet changes (spaces, a trailing ".0") and refuses damaged values instead of guessing:
    scientific notation (6.9E+11) and EAN/UPC codes that lost leading zeros (7 or 11 digits)."""
    value = (raw or "").strip().replace(" ", "")
    if not value:
        return ""
    if SCIENTIFIC.match(value):
        raise ValueError(f"barcode {value} was changed by the spreadsheet into a short number "
                         "(format the column as Text and type the full barcode)")
    if re.fullmatch(r"\d+\.0+", value):
        value = value.split(".")[0]
    if value.isdigit() and len(value) in (7, 11):
        raise ValueError(f"barcode {value} has {len(value)} digits - it looks like the spreadsheet removed a "
                         "leading 0 (format the column as Text)")
    return value
