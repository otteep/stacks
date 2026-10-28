"""High-level operations: turn an ISBN into a Book (and a Copy)."""

from dataclasses import dataclass

from django.db import transaction

from ..models import Book, Copy
from . import covers, lookup
from .sortkeys import author_sort_key


@dataclass
class AddResult:
    book: Book
    copy: Copy | None
    book_created: bool
    already_owned: int  # copies that existed before this call


def _fetch_cover(book: Book, urls: list[str], isbn13: str) -> bool:
    for url in urls:
        data = covers.download(url)
        if data and covers.save_cover(book.pk, data):
            return True
    # Open Library had no cover; Google Books may.
    if not any("books.google" in u or "googleusercontent" in u for u in urls):
        google = lookup.from_google_books(isbn13)
        if google:
            for url in google.cover_urls:
                data = covers.download(url)
                if data and covers.save_cover(book.pk, data):
                    return True
    return False


def get_or_create_book(isbn13: str) -> tuple[Book, bool]:
    """Return the Book for an ISBN, looking it up and downloading a cover if new.

    A lookup miss still creates a stub (flagged ``needs_review``) so the scan is
    never lost; the user fixes it later from the review queue.
    """
    existing = Book.objects.filter(isbn13=isbn13).first()
    if existing:
        return existing, False

    meta = lookup.lookup(isbn13)
    book = Book(
        isbn13=isbn13,
        title=meta.title or f"ISBN {isbn13}",
        subtitle=meta.subtitle,
        authors="; ".join(meta.authors),
        publisher=meta.publisher,
        published_year=meta.published_year,
        page_count=meta.page_count,
        language=meta.language,
        description=meta.description,
        source=meta.source or Book.Source.MANUAL,
        needs_review=not meta.complete,
    )
    book.author_sort = author_sort_key(book.authors)
    with transaction.atomic():
        book.save()

    # A missing cover alone is not worth a review flag.
    if _fetch_cover(book, meta.cover_urls, isbn13):
        book.has_cover = True
        book.save(update_fields=["has_cover", "updated_at"])
    return book, True


def add_copy_by_isbn(isbn13: str, *, location: str = "", add_duplicate: bool = False) -> AddResult:
    """Add a book by ISBN.

    If the book is already in the library and ``add_duplicate`` is False, no
    copy is created and the caller should ask the user whether to add another.
    """
    book, created = get_or_create_book(isbn13)
    owned = book.copies.count()
    if owned and not add_duplicate:
        return AddResult(book=book, copy=None, book_created=created, already_owned=owned)
    copy = Copy.objects.create(book=book, location=location)
    return AddResult(book=book, copy=copy, book_created=created, already_owned=owned)
