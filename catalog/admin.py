from django.contrib import admin

from .models import Book, Copy, Tag


class CopyInline(admin.TabularInline):
    model = Copy
    extra = 0


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "authors", "isbn13", "published_year", "needs_review")
    list_filter = ("needs_review", "source")
    search_fields = ("title", "authors", "isbn13", "publisher")
    inlines = [CopyInline]


@admin.register(Copy)
class CopyAdmin(admin.ModelAdmin):
    list_display = ("book", "format", "location", "condition")
    list_filter = ("format", "condition")
    search_fields = ("book__title", "location", "notes")


admin.site.register(Tag)
