"""Cover image download, validation and storage.

Covers are fetched once and stored locally (never hot-linked) so they keep
working if a remote service changes. Downloads are restricted to a small
host allowlist, redirects are re-checked at every hop, and the body is size
capped before Pillow ever sees it.
"""

import io
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

from .lookup import user_agent

log = logging.getLogger(__name__)

THUMB_PIXELS = 360
MAX_REDIRECTS = 3
Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs


def cover_path(book_id: int, thumb: bool = False) -> Path:
    suffix = "_thumb" if thumb else ""
    return Path(settings.COVERS_DIR) / f"{book_id}{suffix}.jpg"


def _host_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in settings.COVER_ALLOWED_HOSTS)


def download(url: str) -> bytes | None:
    """Fetch image bytes from an allowlisted https URL, or None on any problem."""
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not _host_allowed(current):
                log.warning("Cover host not allowed: %s", current)
                return None
            with requests.get(
                current,
                headers={"User-Agent": user_agent()},
                timeout=settings.LOOKUP_TIMEOUT,
                stream=True,
                allow_redirects=False,
            ) as response:
                if response.is_redirect:
                    current = requests.compat.urljoin(current, response.headers.get("Location", ""))
                    continue
                if response.status_code != 200:
                    return None
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > settings.COVER_MAX_BYTES:
                    return None
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    body.extend(chunk)
                    if len(body) > settings.COVER_MAX_BYTES:
                        return None
                return bytes(body)
    except requests.RequestException as exc:
        log.info("Cover download failed for %s: %s", url, exc)
    return None


def save_cover(book_id: int, data: bytes) -> bool:
    """Validate, normalise to JPEG, and write the full-size and thumbnail files."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode != "RGB":
                background = Image.new("RGB", image.size, (255, 255, 255))
                rgba = image.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                image = background
            # Placeholder "no cover" images are tiny; real covers are larger.
            if min(image.size) < 50:
                return False
            full = image.copy()
            full.thumbnail((settings.COVER_MAX_PIXELS, settings.COVER_MAX_PIXELS))
            full.save(cover_path(book_id), "JPEG", quality=85, optimize=True)
            thumb = image.copy()
            thumb.thumbnail((THUMB_PIXELS, THUMB_PIXELS))
            thumb.save(cover_path(book_id, thumb=True), "JPEG", quality=80, optimize=True)
        return True
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        log.info("Rejected cover for book %s: %s", book_id, exc)
        return False


def delete_cover(book_id: int) -> None:
    for thumb in (False, True):
        cover_path(book_id, thumb).unlink(missing_ok=True)
