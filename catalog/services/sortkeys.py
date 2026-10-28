"""Helpers that make sorting and searching behave the way a human expects.

SQLite's built-in collation and LIKE only fold ASCII case, so Cyrillic,
accented Latin, etc. would sort and search poorly. We precompute folded keys
in Python and store them alongside the display values.
"""

import re
import unicodedata

_ARTICLES = ("the ", "a ", "an ")
_PARTICLES = {"de", "del", "della", "der", "di", "da", "dos", "du", "la", "le", "van", "von", "bin", "ibn", "al", "el"}
_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def fold(text: str) -> str:
    """Casefold, strip accents, collapse whitespace and punctuation noise."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_sort_key(title: str) -> str:
    folded = fold(title)
    for article in _ARTICLES:
        if folded.startswith(article) and len(folded) > len(article):
            return folded[len(article):]
    return folded


def split_authors(authors: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]", authors or "") if part.strip()]


def author_sort_key(authors: str) -> str:
    """Sort key from the first author: 'Fyodor Dostoevsky' -> 'dostoevsky fyodor'.

    Handles 'Last, First' input, name particles ('Ludwig van Beethoven' ->
    'van beethoven ludwig') and generational suffixes. It is a heuristic; the
    sort key is stored separately so it can be corrected when it guesses wrong.
    """
    names = split_authors(authors)
    if not names:
        return ""
    name = names[0]

    if "," in name:
        last, _, first = name.partition(",")
        return fold(f"{last} {first}")

    words = name.split()
    while len(words) > 1 and fold(words[-1]) in _SUFFIXES:
        words.pop()
    if len(words) == 1:
        return fold(words[0])

    # Walk back over particles so 'van Gogh' stays together.
    i = len(words) - 1
    while i > 1 and fold(words[i - 1]) in _PARTICLES:
        i -= 1
    surname = " ".join(words[i:])
    given = " ".join(words[:i])
    return fold(f"{surname} {given}")
