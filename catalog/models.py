from django.conf import settings
from django.db import models
from django.urls import reverse

from .services import isbn as isbn_utils
from .services.sortkeys import author_sort_key, fold, title_sort_key


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Book(models.Model):
    """An edition: the ISBN-level facts that are identical for every copy."""

    class Source(models.TextChoices):
        OPEN_LIBRARY = "openlibrary", "Open Library"
        GOOGLE = "google", "Google Books"
        MANUAL = "manual", "Manual"

    isbn13 = models.CharField(
        "ISBN-13", max_length=13, unique=True, null=True, blank=True,
        help_text="Leave blank for books without an ISBN.",
    )
    title = models.CharField(max_length=500)
    subtitle = models.CharField(max_length=500, blank=True)
    authors = models.CharField(
        max_length=500, blank=True, help_text="Separate multiple authors with a semicolon.",
    )
    publisher = models.CharField(max_length=200, blank=True)
    published_year = models.PositiveSmallIntegerField(null=True, blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    language = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)

    has_cover = models.BooleanField(default=False)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    needs_review = models.BooleanField(
        default=False, help_text="Metadata was incomplete or not found; check and fix it.",
    )

    # Derived, stored so SQLite can sort and search them cheaply.
    title_sort = models.CharField(max_length=500, blank=True, editable=False)
    author_sort = models.CharField(
        max_length=500, blank=True,
        help_text="Used for sorting. Filled in automatically; fix it if it guessed wrong.",
    )
    search_text = models.TextField(blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title_sort"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # A blank ISBN must be stored as NULL so the unique constraint ignores it.
        self.isbn13 = isbn_utils.normalize(self.isbn13) if self.isbn13 else None
        self.title_sort = title_sort_key(self.title)
        if not self.author_sort:
            self.author_sort = author_sort_key(self.authors)
        self.search_text = fold(" ".join([
            self.title, self.subtitle, self.authors, self.publisher, self.isbn13 or "",
        ]))
        super().save(*args, **kwargs)

    @property
    def isbn10(self):
        return isbn_utils.to_10(self.isbn13) if self.isbn13 else None

    @property
    def author_list(self):
        return [a.strip() for a in self.authors.replace("\n", ";").split(";") if a.strip()]


class Copy(models.Model):
    """One physical copy you own."""

    class Format(models.TextChoices):
        HARDCOVER = "hardcover", "Hardcover"
        PAPERBACK = "paperback", "Paperback"
        MASS_MARKET = "mass_market", "Mass market"
        OTHER = "other", "Other"

    class Condition(models.TextChoices):
        NEW = "new", "New"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"
        POOR = "poor", "Poor"

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="copies")
    format = models.CharField(max_length=20, choices=Format.choices, blank=True)
    condition = models.CharField(max_length=20, choices=Condition.choices, blank=True)
    location = models.CharField(
        max_length=200, blank=True, help_text='For example "Study, bookcase 2, shelf 3".',
    )
    acquired_on = models.DateField(null=True, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="copies")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["book__title_sort", "id"]
        verbose_name_plural = "copies"

    def __str__(self):
        return f"{self.book.title} ({self.get_format_display() or 'copy'})"

    def get_absolute_url(self):
        return reverse("copy_detail", args=[self.pk])


class UserSettings(models.Model):
    """Per-account preferences. One row, created the first time a setting is saved."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="catalog_settings",
    )
    theme = models.CharField(max_length=40, default="paper")

    class Meta:
        verbose_name_plural = "user settings"

    def __str__(self):
        return f"Settings for {self.user}"
