"""Named looks for the catalog.

Add a theme in two places:

1. Append a ``Theme`` to ``THEMES`` below.
2. Add a ``[data-theme="<id>"]`` block in ``stacks.css`` that sets the same
   custom properties as ``[data-theme="paper"]``. Tints (rules, hovers, notices)
   are derived from those properties, and can be overridden in the same block.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    description: str
    background: str
    color_scheme: str = "light"


# Order is the order shown on the settings page. The first theme is the default.
THEMES: tuple[Theme, ...] = (
    Theme(
        id="paper",
        label="Paper",
        description="Warm stock, a ruled ground, and the Archive’s type.",
        background="#f5f0e8",
    ),
)


def iter_themes() -> tuple[Theme, ...]:
    return tuple(THEMES)


def get_theme(theme_id: str | None) -> Theme:
    for theme in THEMES:
        if theme.id == theme_id:
            return theme
    return THEMES[0]
