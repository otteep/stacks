"""ISBN parsing, validation and conversion."""

import re

_STRIP = re.compile(r"[\s\-]")


def clean(raw: str) -> str:
    """Remove spaces/hyphens, upper-case a trailing X, drop a leading 'ISBN'."""
    raw = (raw or "").strip()
    raw = re.sub(r"^isbn(-1[03])?:?", "", raw, flags=re.IGNORECASE)
    return _STRIP.sub("", raw).upper()


def _check_digit_10(first9: str) -> str:
    total = sum((10 - i) * int(d) for i, d in enumerate(first9))
    check = (11 - total % 11) % 11
    return "X" if check == 10 else str(check)


def _check_digit_13(first12: str) -> str:
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def is_valid_10(isbn: str) -> bool:
    return bool(re.fullmatch(r"\d{9}[\dX]", isbn)) and _check_digit_10(isbn[:9]) == isbn[9]


def is_valid_13(isbn: str) -> bool:
    return bool(re.fullmatch(r"\d{13}", isbn)) and _check_digit_13(isbn[:12]) == isbn[12]


def to_13(isbn10: str) -> str:
    body = "978" + isbn10[:9]
    return body + _check_digit_13(body)


def to_10(isbn13: str) -> str | None:
    """Only 978-prefixed ISBN-13s have an ISBN-10 equivalent."""
    if not isbn13.startswith("978"):
        return None
    body = isbn13[3:12]
    return body + _check_digit_10(body)


def normalize(raw: str) -> str | None:
    """Return a valid ISBN-13 for any ISBN-10/13 input, or None if invalid."""
    value = clean(raw)
    if is_valid_13(value):
        return value
    if is_valid_10(value):
        return to_13(value)
    return None
