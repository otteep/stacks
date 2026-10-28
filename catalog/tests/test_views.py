import csv
import io
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Book, Copy, Tag
from catalog.services import covers

from .test_services import png_bytes


class BaseViewTest(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(COVERS_DIR=Path(tmp.name))
        override.enable()
        self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_user("isaac", password="correct horse battery")
        self.client.force_login(self.user)

    def make(self, title, authors="", year=None, location="", **book_extra):
        book = Book.objects.create(title=title, authors=authors, published_year=year, **book_extra)
        return Copy.objects.create(book=book, location=location)


class AuthTests(TestCase):
    def test_every_page_requires_login(self):
        for name, args in [
            ("library", []), ("add", []), ("add_manual", []), ("review", []),
            ("export", []), ("copy_detail", [1]), ("copy_edit", [1]), ("cover", [1]),
        ]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn("/login/", response["Location"], name)

    def test_post_endpoints_require_login(self):
        self.assertEqual(self.client.post(reverse("add"), {"isbn": "9780306406157"}).status_code, 302)
        self.assertEqual(self.client.post(reverse("copy_delete", args=[1])).status_code, 302)

    def test_admin_requires_login(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)

    def test_healthz_is_public(self):
        self.assertEqual(self.client.get(reverse("healthz")).status_code, 200)

    def test_htmx_request_gets_redirect_header_not_a_login_page(self):
        response = self.client.get(reverse("library"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 401)
        self.assertIn("/login/", response["HX-Redirect"])

    def test_login_works(self):
        get_user_model().objects.create_user("u", password="pw-12345678")
        response = self.client.post(reverse("login"), {"username": "u", "password": "pw-12345678"})
        self.assertRedirects(response, reverse("library"))


class LibraryTests(BaseViewTest):
    def setUp(self):
        super().setUp()
        self.karamazov = self.make("The Brothers Karamazov", "Fyodor Dostoevsky", 1880, "Study")
        self.crime = self.make("Crime and Punishment", "Fyodor Dostoevsky", 1866, "Study")
        self.zhivago = self.make("Doctor Zhivago", "Boris Pasternak", 1957, "Bedroom")
        self.war = self.make("Война и мир", "Лев Толстой", 1869, "Bedroom")
        self.undated = self.make("Undated Pamphlet", "Anon")

    def titles(self, **params):
        response = self.client.get(reverse("library"), params)
        self.assertEqual(response.status_code, 200)
        return [c.book.title for c in response.context["page"].object_list]

    def test_default_sort_ignores_leading_article(self):
        titles = self.titles()
        self.assertLess(titles.index("The Brothers Karamazov"), titles.index("Crime and Punishment"))

    def test_sort_by_author_uses_surname(self):
        titles = self.titles(sort="author")
        self.assertEqual(titles[0], "Undated Pamphlet")  # "anon"
        self.assertLess(titles.index("The Brothers Karamazov"), titles.index("Doctor Zhivago"))
        self.assertLess(titles.index("Crime and Punishment"), titles.index("Doctor Zhivago"))

    def test_sort_by_year_puts_missing_years_last_in_both_directions(self):
        asc = self.titles(sort="year")
        self.assertEqual(asc[0], "Crime and Punishment")
        self.assertEqual(asc[-1], "Undated Pamphlet")
        desc = self.titles(sort="year", dir="desc")
        self.assertEqual(desc[0], "Doctor Zhivago")
        self.assertEqual(desc[-1], "Undated Pamphlet")

    def test_unknown_sort_falls_back_to_default(self):
        self.assertEqual(self.titles(sort="; DROP TABLE"), self.titles())

    def test_every_sort_option_runs(self):
        for key in ("title", "author", "year", "added", "location", "publisher",
                    "pages", "format", "condition", "price", "acquired"):
            for direction in ("asc", "desc"):
                self.assertEqual(len(self.titles(sort=key, dir=direction)), 5, (key, direction))

    def test_search_is_case_and_accent_insensitive(self):
        self.assertEqual(self.titles(q="dostoevsky"), ["The Brothers Karamazov", "Crime and Punishment"])
        self.assertEqual(self.titles(q="ВОЙНА"), ["Война и мир"])
        self.assertEqual(self.titles(q="война И МИР"), ["Война и мир"])

    def test_search_terms_are_anded(self):
        self.assertEqual(self.titles(q="dostoevsky crime"), ["Crime and Punishment"])

    def test_search_matches_location_notes_and_tags(self):
        self.zhivago.notes = "signed by the translator"
        self.zhivago.save()
        tag = Tag.objects.create(name="winter-reading")
        self.crime.tags.add(tag)
        self.assertEqual(self.titles(q="translator"), ["Doctor Zhivago"])
        self.assertEqual(self.titles(q="bedroom"), ["Doctor Zhivago", "Война и мир"])
        self.assertEqual(self.titles(q="winter"), ["Crime and Punishment"])

    def test_filters(self):
        self.assertEqual(self.titles(location="Bedroom"), ["Doctor Zhivago", "Война и мир"])
        self.zhivago.format = Copy.Format.PAPERBACK
        self.zhivago.save()
        self.assertEqual(self.titles(format="paperback"), ["Doctor Zhivago"])

    def test_tag_filter_does_not_duplicate_rows(self):
        for name in ("a", "b"):
            self.crime.tags.add(Tag.objects.create(name=name))
        self.assertEqual(self.titles(q="crime"), ["Crime and Punishment"])

    def test_htmx_returns_fragment_only(self):
        response = self.client.get(reverse("library"), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(response, "catalog/_results.html")
        self.assertTemplateNotUsed(response, "catalog/library.html")

    def test_pagination(self):
        with self.settings(PAGE_SIZE=2):
            response = self.client.get(reverse("library"), {"page": 2})
            self.assertEqual(len(response.context["page"].object_list), 2)
            self.assertContains(response, "Page 2 of 3")

    def test_book_titles_are_html_escaped(self):
        self.make("<script>alert(1)</script>")
        response = self.client.get(reverse("library"))
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")


class AddFlowTests(BaseViewTest):
    @mock.patch("catalog.services.books.covers.download", return_value=None)
    @mock.patch("catalog.services.lookup._get_json", return_value=None)
    def test_add_remembers_location_and_flags_misses(self, *_):
        response = self.client.post(reverse("add"), {"isbn": "0-306-40615-2", "location": "Study, shelf 1"})
        # Don't fetch the redirect target here: that would consume the flash message.
        self.assertRedirects(response, reverse("add"), fetch_redirect_response=False)
        self.assertEqual(Copy.objects.get().location, "Study, shelf 1")
        page = self.client.get(reverse("add"))
        self.assertContains(page, 'value="Study, shelf 1"')
        self.assertContains(page, "couldn")  # the "couldn't find full details" notice

    def test_invalid_isbn_is_rejected_with_message(self):
        response = self.client.post(reverse("add"), {"isbn": "9780306406158"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "isn&#x27;t a valid ISBN")
        self.assertEqual(Book.objects.count(), 0)

    @mock.patch("catalog.services.books.covers.download", return_value=None)
    @mock.patch("catalog.services.lookup._get_json", return_value=None)
    def test_duplicate_asks_then_adds_second_copy(self, *_):
        self.client.post(reverse("add"), {"isbn": "9780306406157"})
        response = self.client.post(reverse("add"), {"isbn": "9780306406157"})
        self.assertContains(response, "You already own this")
        self.assertEqual(Copy.objects.count(), 1)
        self.client.post(reverse("add"), {"isbn": "9780306406157", "add_duplicate": "1"})
        self.assertEqual(Copy.objects.count(), 2)

    @mock.patch("catalog.services.books.covers.download", return_value=None)
    @mock.patch("catalog.services.lookup._get_json")
    def test_hostile_title_from_api_cannot_inject_html(self, get_json, _):
        get_json.side_effect = [
            {"ISBN:9780306406157": {
                "title": '"><img src=x onerror=alert(1)>', "authors": [{"name": "A B"}],
                "publishers": [{"name": "P"}], "publish_date": "2001",
            }},
            None,
        ]
        self.client.post(reverse("add"), {"isbn": "9780306406157"})
        page = self.client.get(reverse("add"))
        self.assertNotContains(page, "<img src=x")
        self.assertContains(page, "&lt;img src=x")

    def test_manual_add_without_isbn(self):
        response = self.client.post(reverse("add_manual"), {
            "book-title": "Hand-bound Diary", "book-authors": "Me",
            "copy-location": "Desk", "copy-tags": "journal, handmade",
        })
        copy = Copy.objects.get()
        self.assertRedirects(response, copy.get_absolute_url())
        self.assertIsNone(copy.book.isbn13)
        self.assertEqual(sorted(t.name for t in copy.tags.all()), ["handmade", "journal"])

    def test_two_manual_books_without_isbn_do_not_collide(self):
        for title in ("One", "Two"):
            self.client.post(reverse("add_manual"), {"book-title": title})
        self.assertEqual(Book.objects.count(), 2)


class EditDeleteTests(BaseViewTest):
    def setUp(self):
        super().setUp()
        self.copy = self.make("Old Title", "Jane Austen", 1813, "Study", isbn13="9780306406157", needs_review=True)

    def test_edit_updates_book_and_copy_and_clears_review_flag(self):
        response = self.client.post(reverse("copy_edit", args=[self.copy.pk]), {
            "book-title": "Pride and Prejudice", "book-authors": "Jane Austen",
            "book-author_sort": "austen jane", "book-isbn13": "978-0-306-40615-7",
            "copy-location": "Living room", "copy-price": "12.50",
            "copy-acquired_on": "2024-05-01", "copy-format": "hardcover", "copy-tags": "classic",
        })
        self.assertRedirects(response, self.copy.get_absolute_url())
        self.copy.refresh_from_db()
        self.copy.book.refresh_from_db()
        self.assertEqual(self.copy.book.title, "Pride and Prejudice")
        self.assertEqual(self.copy.book.title_sort, "pride and prejudice")
        self.assertFalse(self.copy.book.needs_review)
        self.assertEqual(self.copy.location, "Living room")
        self.assertEqual(self.copy.price, Decimal("12.50"))
        self.assertEqual(self.copy.acquired_on, date(2024, 5, 1))

    def test_changing_authors_recomputes_untouched_sort_key(self):
        self.client.post(reverse("copy_edit", args=[self.copy.pk]), {
            "book-title": "Old Title", "book-authors": "Charlotte Bronte",
            "book-author_sort": self.copy.book.author_sort, "copy-location": "Study",
        })
        self.copy.book.refresh_from_db()
        self.assertEqual(self.copy.book.author_sort, "bronte charlotte")

    def test_manually_set_sort_key_is_preserved(self):
        self.client.post(reverse("copy_edit", args=[self.copy.pk]), {
            "book-title": "Old Title", "book-authors": "Jane Austen",
            "book-author_sort": "zzz custom", "copy-location": "Study",
        })
        self.copy.book.refresh_from_db()
        self.assertEqual(self.copy.book.author_sort, "zzz custom")

    def test_isbn_clash_is_reported(self):
        other = self.make("Other", isbn13="9780804429573")
        response = self.client.post(reverse("copy_edit", args=[other.pk]), {
            "book-title": "Other", "book-isbn13": "9780306406157", "copy-location": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Already in your library")

    def test_delete_last_copy_removes_book_and_cover(self):
        covers.save_cover(self.copy.book.pk, png_bytes())
        book_id = self.copy.book.pk
        response = self.client.post(reverse("copy_delete", args=[self.copy.pk]))
        self.assertRedirects(response, reverse("library"))
        self.assertFalse(Book.objects.filter(pk=book_id).exists())
        self.assertFalse(covers.cover_path(book_id).exists())

    def test_delete_one_of_two_copies_keeps_book(self):
        Copy.objects.create(book=self.copy.book, location="Attic")
        self.client.post(reverse("copy_delete", args=[self.copy.pk]))
        self.assertEqual(Book.objects.count(), 1)
        self.assertEqual(Copy.objects.count(), 1)

    def test_delete_requires_post(self):
        self.assertEqual(self.client.get(reverse("copy_delete", args=[self.copy.pk])).status_code, 200)
        self.assertEqual(Copy.objects.count(), 1)

    def test_clear_review_flag(self):
        self.client.post(reverse("clear_review", args=[self.copy.book.pk]))
        self.copy.book.refresh_from_db()
        self.assertFalse(self.copy.book.needs_review)

    def test_review_queue_lists_flagged_only(self):
        self.make("Fine Book")
        response = self.client.get(reverse("review"))
        self.assertContains(response, "Old Title")
        self.assertNotContains(response, "Fine Book")


class CoverAndExportTests(BaseViewTest):
    def test_cover_served_privately(self):
        copy = self.make("Covered")
        covers.save_cover(copy.book.pk, png_bytes())
        response = self.client.get(reverse("cover", args=[copy.book.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertIn("private", response["Cache-Control"])
        response.close()

    def test_missing_cover_is_404(self):
        self.assertEqual(self.client.get(reverse("cover", args=[9999])).status_code, 404)

    def test_csv_export_and_formula_injection_guard(self):
        copy = self.make("=HYPERLINK(\"http://evil\")", "Anna, Karenina", 1877, "Study")
        copy.price = Decimal("9.99")
        copy.save()
        response = self.client.get(reverse("export"))
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0][0], "title")
        self.assertTrue(rows[1][0].startswith("'="))
        self.assertEqual(rows[1][2], "Anna, Karenina")
        self.assertEqual(rows[1][12], "9.99")

    def test_export_respects_filters(self):
        self.make("Keep", location="Study")
        self.make("Skip", location="Attic")
        response = self.client.get(reverse("export"), {"location": "Study"})
        self.assertContains(response, "Keep")
        self.assertNotContains(response, "Skip")


class BootstrapUserTests(TestCase):
    def test_creates_user_once_from_env(self):
        env = {"STACKS_ADMIN_USER": "owner", "STACKS_ADMIN_PASSWORD": "long-enough-pw"}
        with mock.patch.dict("os.environ", env):
            call_command("bootstrap_user")
            call_command("bootstrap_user")
        User = get_user_model()
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(User.objects.get(username="owner").check_password("long-enough-pw"))

    def test_does_not_touch_existing_users(self):
        get_user_model().objects.create_user("existing", password="x")
        with mock.patch.dict("os.environ", {"STACKS_ADMIN_USER": "new", "STACKS_ADMIN_PASSWORD": "long-enough-pw"}):
            call_command("bootstrap_user")
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_short_password_is_refused(self):
        with mock.patch.dict("os.environ", {"STACKS_ADMIN_USER": "owner", "STACKS_ADMIN_PASSWORD": "short"}):
            call_command("bootstrap_user")
        self.assertEqual(get_user_model().objects.count(), 0)
