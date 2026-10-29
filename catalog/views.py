import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from django.conf import settings

from .forms import BookForm, CopyForm, IsbnForm, ThemeForm
from .models import Book, Copy, Tag, UserSettings
from .services import books as book_service
from .services import covers
from .services.sortkeys import fold
from .themes import get_theme, iter_themes

# Settings is a tabbed page. A new section is a new entry here plus a branch
# in catalog/templates/catalog/settings.html.
SETTINGS_TABS = (
    ("themes", "Themes"),
)

# sort key -> (label, order_by fields). A trailing "?" marks a nullable column,
# which always sorts nulls last. Only the first field flips for descending order;
# the rest stay ascending as stable tie-breakers.
SORTS = {
    "title": ("Title", ["book__title_sort", "id"]),
    "author": ("Author", ["book__author_sort", "book__title_sort"]),
    "year": ("Year published", ["book__published_year?", "book__title_sort"]),
    "added": ("Date added", ["created_at", "id"]),
    "location": ("Location", ["location", "book__title_sort"]),
    "publisher": ("Publisher", ["book__publisher", "book__title_sort"]),
    "pages": ("Page count", ["book__page_count?", "book__title_sort"]),
    "format": ("Format", ["format", "book__title_sort"]),
    "condition": ("Condition", ["condition", "book__title_sort"]),
    "price": ("Price paid", ["price?", "book__title_sort"]),
    "acquired": ("Date acquired", ["acquired_on?", "book__title_sort"]),
}
DEFAULT_SORT = "title"


def _ordering(sort: str, direction: str):
    ordering = []
    for index, spec in enumerate(SORTS[sort][1]):
        nullable = spec.endswith("?")
        field = F(spec.rstrip("?"))
        descending = direction == "desc" and index == 0
        if nullable:
            ordering.append(field.desc(nulls_last=True) if descending else field.asc(nulls_last=True))
        else:
            ordering.append(field.desc() if descending else field.asc())
    return ordering


def filtered_copies(params):
    queryset = Copy.objects.select_related("book").prefetch_related("tags")

    query = fold(params.get("q", ""))
    for term in query.split():
        # book.search_text is pre-folded, so Cyrillic and accents match
        # case- and accent-insensitively; location/notes use plain icontains.
        queryset = queryset.filter(
            Q(book__search_text__contains=term)
            | Q(location__icontains=term)
            | Q(notes__icontains=term)
            | Q(tags__name__icontains=term)
        )
    if params.get("format"):
        queryset = queryset.filter(format=params["format"])
    if params.get("condition"):
        queryset = queryset.filter(condition=params["condition"])
    if params.get("location"):
        queryset = queryset.filter(location=params["location"])
    if params.get("tag"):
        queryset = queryset.filter(tags__name=params["tag"])

    sort = params.get("sort") if params.get("sort") in SORTS else DEFAULT_SORT
    direction = "desc" if params.get("dir") == "desc" else "asc"
    return queryset.distinct().order_by(*_ordering(sort, direction)), sort, direction


@require_GET
def library(request):
    queryset, sort, direction = filtered_copies(request.GET)
    page = Paginator(queryset, settings.PAGE_SIZE).get_page(request.GET.get("page"))

    preserved = request.GET.copy()
    preserved.pop("page", None)
    context = {
        "page": page,
        "total": page.paginator.count,
        "params": request.GET,
        "querystring": preserved.urlencode(),
        "view_mode": "grid" if request.GET.get("view") == "grid" else "list",
        "sort": sort,
        "direction": direction,
        "sorts": [(key, label) for key, (label, _) in SORTS.items()],
        "formats": Copy.Format.choices,
        "conditions": Copy.Condition.choices,
        "locations": _distinct_locations(),
        "tags": Tag.objects.filter(copies__isnull=False).distinct(),
        "review_count": Book.objects.filter(needs_review=True).count(),
    }
    template = "catalog/_results.html" if request.headers.get("HX-Request") else "catalog/library.html"
    return render(request, template, context)


def _distinct_locations():
    return list(
        Copy.objects.exclude(location="").values_list("location", flat=True).distinct().order_by("location")
    )


@login_required
def add_by_isbn(request):
    initial_location = request.session.get("last_location", "")
    if request.method == "POST":
        form = IsbnForm(request.POST)
        if form.is_valid():
            isbn13 = form.cleaned_data["isbn"]
            location = form.cleaned_data["location"].strip()
            request.session["last_location"] = location
            add_duplicate = request.POST.get("add_duplicate") == "1"
            result = book_service.add_copy_by_isbn(isbn13, location=location, add_duplicate=add_duplicate)

            if result.copy is None:
                # Already owned: ask before creating another copy.
                return render(request, "catalog/confirm_duplicate.html", {
                    "book": result.book, "owned": result.already_owned,
                    "isbn": isbn13, "location": location,
                })

            title = result.book.title
            edit_url = reverse("copy_edit", args=[result.copy.pk])
            if result.book.needs_review:
                # Titles come from external APIs, so they are escaped by format_html.
                messages.warning(request, format_html(
                    "Added “{}” but couldn’t find full details. "
                    '<a href="{}">Fix it now</a> or find it in the review queue.',
                    title, edit_url,
                ))
            else:
                messages.success(request, format_html(
                    'Added “{}”. <a href="{}">Edit</a>', title, edit_url,
                ))
            return redirect("add")
    else:
        form = IsbnForm(initial={"location": initial_location})
    return render(request, "catalog/add.html", {"form": form, "locations": _distinct_locations()})


@login_required
def add_manual(request):
    if request.method == "POST":
        book_form = BookForm(request.POST, request.FILES, prefix="book")
        copy_form = CopyForm(request.POST, prefix="copy")
        if book_form.is_valid() and copy_form.is_valid():
            book = book_form.save()
            book.source = Book.Source.MANUAL
            book.save(update_fields=["source", "updated_at"])
            copy = copy_form.save(commit=False)
            copy.book = book
            copy.save()
            copy_form.save_tags(copy)
            messages.success(request, f"Added “{book.title}”.")
            return redirect(copy.get_absolute_url())
    else:
        book_form = BookForm(prefix="book")
        copy_form = CopyForm(prefix="copy", initial={"location": request.session.get("last_location", "")})
    return render(request, "catalog/edit.html", {
        "book_form": book_form, "copy_form": copy_form, "creating": True,
        "locations": _distinct_locations(), "all_tags": Tag.objects.all(),
    })


@require_GET
def copy_detail(request, pk):
    copy = get_object_or_404(Copy.objects.select_related("book").prefetch_related("tags"), pk=pk)
    return render(request, "catalog/detail.html", {
        "copy": copy, "book": copy.book, "sibling_copies": copy.book.copies.exclude(pk=pk),
    })


@login_required
def copy_edit(request, pk):
    copy = get_object_or_404(Copy.objects.select_related("book"), pk=pk)
    if request.method == "POST":
        book_form = BookForm(request.POST, request.FILES, instance=copy.book, prefix="book")
        copy_form = CopyForm(request.POST, instance=copy, prefix="copy")
        if book_form.is_valid() and copy_form.is_valid():
            book_form.save()
            copy_form.save()
            messages.success(request, "Saved.")
            return redirect(copy.get_absolute_url())
    else:
        book_form = BookForm(instance=copy.book, prefix="book")
        copy_form = CopyForm(instance=copy, prefix="copy")
    return render(request, "catalog/edit.html", {
        "book_form": book_form, "copy_form": copy_form, "copy": copy, "book": copy.book,
        "locations": _distinct_locations(), "all_tags": Tag.objects.all(),
    })


@login_required
def copy_delete(request, pk):
    copy = get_object_or_404(Copy.objects.select_related("book"), pk=pk)
    if request.method == "POST":
        book = copy.book
        title = book.title
        copy.delete()
        # An edition with no copies left is just clutter; remove it and its cover.
        if not book.copies.exists():
            covers.delete_cover(book.pk)
            book.delete()
        messages.success(request, f"Removed “{title}”.")
        return redirect("library")
    return render(request, "catalog/confirm_delete.html", {"copy": copy, "book": copy.book})


@require_GET
def review_queue(request):
    items = Copy.objects.filter(book__needs_review=True).select_related("book").order_by("-created_at")
    return render(request, "catalog/review.html", {"items": items})


@require_POST
def clear_review(request, pk):
    book = get_object_or_404(Book, pk=pk)
    book.needs_review = False
    book.save(update_fields=["needs_review", "updated_at"])
    return redirect("review")


@require_GET
def cover(request, book_id):
    path = covers.cover_path(book_id, thumb=request.GET.get("thumb") == "1")
    if not path.exists():
        raise Http404
    response = FileResponse(open(path, "rb"), content_type="image/jpeg")
    # Covers are behind login, so keep them out of shared caches.
    response["Cache-Control"] = "private, max-age=86400"
    return response


@require_GET
def export_csv(request):
    queryset, _, _ = filtered_copies(request.GET)
    stamp = timezone.localdate().isoformat()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="stacks-{stamp}.csv"'
    response.write("﻿")  # BOM so Excel opens UTF-8 correctly
    writer = csv.writer(response)
    writer.writerow([
        "title", "subtitle", "authors", "isbn13", "publisher", "published_year", "page_count",
        "language", "format", "condition", "location", "acquired_on", "price", "tags", "notes",
    ])
    for copy in queryset:
        book = copy.book
        writer.writerow([
            _csv_safe(v) for v in [
                book.title, book.subtitle, book.authors, book.isbn13 or "", book.publisher,
                book.published_year or "", book.page_count or "", book.language,
                copy.format, copy.condition, copy.location, copy.acquired_on or "",
                copy.price if copy.price is not None else "",
                "; ".join(t.name for t in copy.tags.all()), copy.notes,
            ]
        ])
    return response


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in exported text cells."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def _active_tab(requested: str | None) -> str:
    tab_ids = {tab_id for tab_id, _label in SETTINGS_TABS}
    if requested in tab_ids:
        return requested
    return SETTINGS_TABS[0][0]


@require_http_methods(["GET", "POST"])
def settings_page(request):
    active_tab = _active_tab(request.POST.get("tab") if request.method == "POST" else request.GET.get("tab"))
    saved_theme = UserSettings.objects.filter(user=request.user).values_list("theme", flat=True).first()
    if request.method == "POST" and active_tab == "themes":
        form = ThemeForm(request.POST)
        if form.is_valid():
            chosen = get_theme(form.cleaned_data["theme"])
            UserSettings.objects.update_or_create(user=request.user, defaults={"theme": chosen.id})
            messages.success(request, f"{chosen.label} is now the theme.")
            return redirect(f"{reverse('settings')}?tab=themes")
    else:
        form = ThemeForm(initial={"theme": get_theme(saved_theme).id})
    return render(request, "catalog/settings.html", {
        "settings_tabs": SETTINGS_TABS,
        "active_tab": active_tab,
        "theme_form": form,
        "themes": iter_themes(),
    })
