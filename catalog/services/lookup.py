"""Book metadata lookup: Open Library first, Google Books as the fallback.

Every function here fails soft. Network errors, timeouts and odd payloads
produce ``None`` / empty fields rather than exceptions, because a lookup miss
must never block adding a book.
"""

import logging
import re
from dataclasses import dataclass, field

import requests
from django.conf import settings

log = logging.getLogger(__name__)

OPEN_LIBRARY_URL = "https://openlibrary.org/api/books"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"


def user_agent() -> str:
    contact = f" ({settings.STACKS_CONTACT})" if settings.STACKS_CONTACT else ""
    return f"Stacks/1.0 self-hosted book catalog{contact}"


@dataclass
class BookMetadata:
    isbn13: str
    title: str = ""
    subtitle: str = ""
    authors: list[str] = field(default_factory=list)
    publisher: str = ""
    published_year: int | None = None
    page_count: int | None = None
    language: str = ""
    description: str = ""
    cover_urls: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def found(self) -> bool:
        return bool(self.title)

    @property
    def complete(self) -> bool:
        """Enough to be useful without a manual check."""
        return bool(self.title and self.authors)


def _year(value) -> int | None:
    match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", str(value or ""))
    return int(match.group(1)) if match else None


def _get_json(url: str, params: dict):
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": user_agent()},
            timeout=settings.LOOKUP_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        log.info("Lookup request to %s failed: %s", url, exc)
        return None


def from_open_library(isbn13: str) -> BookMetadata | None:
    key = f"ISBN:{isbn13}"
    payload = _get_json(OPEN_LIBRARY_URL, {"bibkeys": key, "format": "json", "jscmd": "data"})
    if not isinstance(payload, dict) or key not in payload:
        return None
    data = payload[key] or {}
    meta = BookMetadata(
        isbn13=isbn13,
        title=(data.get("title") or "").strip(),
        subtitle=(data.get("subtitle") or "").strip(),
        authors=[a.get("name", "").strip() for a in data.get("authors", []) if a.get("name")],
        publisher=", ".join(p.get("name", "") for p in data.get("publishers", [])[:1]),
        published_year=_year(data.get("publish_date")),
        page_count=data.get("number_of_pages") if isinstance(data.get("number_of_pages"), int) else None,
        source="openlibrary",
    )
    # Ask for the large cover by ISBN; default=false makes a miss a 404 rather
    # than a 1x1 placeholder.
    meta.cover_urls = [f"https://covers.openlibrary.org/b/isbn/{isbn13}-L.jpg?default=false"]
    return meta if meta.found else None


def from_google_books(isbn13: str) -> BookMetadata | None:
    payload = _get_json(GOOGLE_BOOKS_URL, {"q": f"isbn:{isbn13}", "maxResults": 1})
    if not isinstance(payload, dict) or not payload.get("items"):
        return None
    info = payload["items"][0].get("volumeInfo", {})
    cover = (info.get("imageLinks") or {}).get("thumbnail", "")
    meta = BookMetadata(
        isbn13=isbn13,
        title=(info.get("title") or "").strip(),
        subtitle=(info.get("subtitle") or "").strip(),
        authors=[a.strip() for a in info.get("authors", []) if a.strip()],
        publisher=(info.get("publisher") or "").strip(),
        published_year=_year(info.get("publishedDate")),
        page_count=info.get("pageCount") if isinstance(info.get("pageCount"), int) else None,
        language=(info.get("language") or "").strip(),
        description=(info.get("description") or "").strip(),
        cover_urls=[cover.replace("http://", "https://", 1).replace("&edge=curl", "")] if cover else [],
        source="google",
    )
    return meta if meta.found else None


def lookup(isbn13: str) -> BookMetadata:
    """Best-effort metadata. Merges Google Books into gaps left by Open Library.

    Always returns a BookMetadata; check ``.found`` / ``.complete``.
    """
    primary = from_open_library(isbn13)
    if primary and primary.complete and primary.publisher and primary.published_year:
        return primary

    secondary = from_google_books(isbn13)
    if not primary:
        return secondary or BookMetadata(isbn13=isbn13)
    if not secondary:
        return primary

    # Fill only what Open Library lacked, keeping its record as the base.
    for name in ("subtitle", "publisher", "published_year", "page_count", "language", "description"):
        if not getattr(primary, name) and getattr(secondary, name):
            setattr(primary, name, getattr(secondary, name))
    if not primary.authors:
        primary.authors = secondary.authors
    primary.cover_urls += secondary.cover_urls
    return primary
