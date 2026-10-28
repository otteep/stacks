from django import forms

from .models import Book, Copy, Tag
from .services import covers, isbn as isbn_utils
from .services.sortkeys import author_sort_key


class IsbnForm(forms.Form):
    isbn = forms.CharField(
        label="ISBN",
        max_length=40,
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "autocomplete": "off", "autofocus": True,
            "placeholder": "Scan or type an ISBN",
        }),
    )
    location = forms.CharField(label="Shelf / location", max_length=200, required=False)

    def clean_isbn(self):
        value = isbn_utils.normalize(self.cleaned_data["isbn"])
        if not value:
            raise forms.ValidationError("That isn't a valid ISBN-10 or ISBN-13 (check the digits).")
        return value


class BookForm(forms.ModelForm):
    # Declared here (not taken from the model) so hyphenated ISBNs and ISBN-10s
    # are accepted and then normalised to ISBN-13.
    isbn13 = forms.CharField(
        label="ISBN", required=False, max_length=40,
        help_text="ISBN-10 or ISBN-13. Leave blank for books without one.",
    )
    cover_upload = forms.ImageField(label="Replace cover", required=False)

    class Meta:
        model = Book
        fields = [
            "title", "subtitle", "authors", "author_sort", "isbn13", "publisher",
            "published_year", "page_count", "language", "description",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remember the derived sort key so we can tell whether the user edited it.
        self._old_authors = self.instance.authors if self.instance.pk else ""
        self._old_sort = self.instance.author_sort if self.instance.pk else ""
        self.fields["author_sort"].required = False

    def clean_isbn13(self):
        raw = self.cleaned_data.get("isbn13")
        if not raw:
            return None
        value = isbn_utils.normalize(raw)
        if not value:
            raise forms.ValidationError("Not a valid ISBN-10 or ISBN-13.")
        clash = Book.objects.filter(isbn13=value).exclude(pk=self.instance.pk).first()
        if clash:
            raise forms.ValidationError(f'Already in your library as "{clash.title}".')
        return value

    def clean_cover_upload(self):
        upload = self.cleaned_data.get("cover_upload")
        if upload and upload.size > 8 * 1024 * 1024:
            raise forms.ValidationError("Cover images must be under 8 MB.")
        return upload

    def save(self, commit=True):
        book = super().save(commit=False)
        sort_untouched = not book.author_sort or (
            book.author_sort == self._old_sort and book.authors != self._old_authors
        )
        if sort_untouched:
            book.author_sort = author_sort_key(book.authors)
        # Saving a reviewed record clears the review flag.
        book.needs_review = False
        if commit:
            book.save()
            upload = self.cleaned_data.get("cover_upload")
            if upload and covers.save_cover(book.pk, upload.read()):
                book.has_cover = True
                book.save(update_fields=["has_cover", "updated_at"])
        return book


class CopyForm(forms.ModelForm):
    tags = forms.CharField(
        required=False, help_text="Comma-separated.",
        widget=forms.TextInput(attrs={"list": "tag-options", "autocomplete": "off"}),
    )

    class Meta:
        model = Copy
        fields = ["format", "condition", "location", "acquired_on", "price", "notes"]
        widgets = {
            "acquired_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "location": forms.TextInput(attrs={"list": "location-options", "autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["tags"].initial = ", ".join(t.name for t in self.instance.tags.all())

    def save(self, commit=True):
        copy = super().save(commit=commit)
        if commit:
            self.save_tags(copy)
        return copy

    def save_tags(self, copy):
        names = {t.strip() for t in self.cleaned_data.get("tags", "").split(",") if t.strip()}
        tags = []
        for name in sorted(names, key=str.casefold):
            existing = Tag.objects.filter(name__iexact=name).first()
            tags.append(existing or Tag.objects.create(name=name[:50]))
        copy.tags.set(tags)
