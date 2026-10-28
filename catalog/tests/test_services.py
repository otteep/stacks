import io
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from catalog.models import Book, Copy
from catalog.services import books as book_service
from catalog.services import covers, lookup

OL_PAYLOAD = {
    "ISBN:9780306406157": {
        "title": "The Brothers Karamazov",
        "authors": [{"name": "Fyodor Dostoevsky"}],
        "publishers": [{"name": "Penguin"}],
        "publish_date": "March 1, 2003",
        "number_of_pages": 840,
    }
}
GB_PAYLOAD = {
    "items": [{
        "volumeInfo": {
            "title": "Obscure Book", "authors": ["A. Writer"], "publisher": "Tiny Press",
            "publishedDate": "1987-05", "pageCount": 200, "language": "en",
            "imageLinks": {"thumbnail": "http://books.google.com/books/content?id=x&edge=curl"},
        }
    }]
}


def png_bytes(size=(200, 300), color=(10, 120, 60)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


class LookupTests(TestCase):
    @mock.patch("catalog.services.lookup._get_json")
    def test_open_library_hit(self, get_json):
        get_json.return_value = OL_PAYLOAD
        meta = lookup.from_open_library("9780306406157")
        self.assertEqual(meta.title, "The Brothers Karamazov")
        self.assertEqual(meta.authors, ["Fyodor Dostoevsky"])
        self.assertEqual(meta.published_year, 2003)
        self.assertEqual(meta.page_count, 840)
        self.assertTrue(meta.cover_urls[0].startswith("https://covers.openlibrary.org/"))

    @mock.patch("catalog.services.lookup._get_json")
    def test_google_fallback_when_open_library_misses(self, get_json):
        get_json.side_effect = [{}, GB_PAYLOAD]
        meta = lookup.lookup("9780306406157")
        self.assertEqual(meta.title, "Obscure Book")
        self.assertEqual(meta.published_year, 1987)
        self.assertTrue(meta.cover_urls[0].startswith("https://"))
        self.assertNotIn("edge=curl", meta.cover_urls[0])

    @mock.patch("catalog.services.lookup._get_json")
    def test_google_fills_gaps_in_open_library_record(self, get_json):
        sparse = {"ISBN:9780306406157": {"title": "Sparse", "authors": [{"name": "X Y"}]}}
        get_json.side_effect = [sparse, GB_PAYLOAD]
        meta = lookup.lookup("9780306406157")
        self.assertEqual(meta.title, "Sparse")  # Open Library stays the base
        self.assertEqual(meta.publisher, "Tiny Press")  # gap filled from Google
        self.assertEqual(meta.page_count, 200)

    @mock.patch("catalog.services.lookup._get_json", return_value=None)
    def test_total_miss_returns_unfound_metadata(self, _):
        meta = lookup.lookup("9780306406157")
        self.assertFalse(meta.found)


class CoverTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(COVERS_DIR=Path(tmp.name))
        override.enable()
        self.addCleanup(override.disable)

    def test_saves_full_and_thumbnail(self):
        self.assertTrue(covers.save_cover(1, png_bytes()))
        self.assertTrue(covers.cover_path(1).exists())
        self.assertTrue(covers.cover_path(1, thumb=True).exists())

    def test_rejects_non_image_bytes(self):
        self.assertFalse(covers.save_cover(2, b"<html>not an image</html>"))

    def test_rejects_tiny_placeholder_image(self):
        self.assertFalse(covers.save_cover(3, png_bytes(size=(1, 1))))

    def test_large_image_is_downscaled(self):
        covers.save_cover(4, png_bytes(size=(3000, 4500)))
        with Image.open(covers.cover_path(4)) as image:
            self.assertLessEqual(max(image.size), 1000)

    def test_host_allowlist(self):
        self.assertTrue(covers._host_allowed("https://covers.openlibrary.org/b/isbn/1-L.jpg"))
        self.assertTrue(covers._host_allowed("https://ia800000.us.archive.org/x.jpg"))
        self.assertFalse(covers._host_allowed("http://covers.openlibrary.org/x.jpg"))  # not https
        self.assertFalse(covers._host_allowed("https://evil.example.com/x.jpg"))
        self.assertFalse(covers._host_allowed("https://covers.openlibrary.org.evil.com/x.jpg"))
        self.assertFalse(covers._host_allowed("https://169.254.169.254/latest/meta-data"))

    @mock.patch("catalog.services.covers.requests.get")
    def test_download_blocks_redirect_to_disallowed_host(self, get):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.is_redirect = True
        response.headers = {"Location": "https://internal.example.com/secret"}
        get.return_value = response
        self.assertIsNone(covers.download("https://covers.openlibrary.org/b/isbn/1-L.jpg"))
        self.assertEqual(get.call_count, 1)  # never followed the bad hop

    @mock.patch("catalog.services.covers.requests.get")
    def test_download_enforces_size_cap(self, get):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.is_redirect = False
        response.status_code = 200
        response.headers = {}
        response.iter_content.return_value = [b"x" * (1024 * 1024)] * 8
        get.return_value = response
        self.assertIsNone(covers.download("https://covers.openlibrary.org/b/isbn/1-L.jpg"))


class AddBookTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(COVERS_DIR=Path(tmp.name))
        override.enable()
        self.addCleanup(override.disable)

    @mock.patch("catalog.services.books.covers.download", return_value=None)
    @mock.patch("catalog.services.lookup._get_json")
    def test_adds_book_and_copy(self, get_json, _):
        get_json.side_effect = [OL_PAYLOAD, None]
        result = book_service.add_copy_by_isbn("9780306406157", location="Study")
        self.assertTrue(result.book_created)
        self.assertEqual(result.copy.location, "Study")
        self.assertEqual(result.book.title, "The Brothers Karamazov")
        self.assertEqual(result.book.author_sort, "dostoevsky fyodor")
        self.assertFalse(result.book.needs_review)

    @mock.patch("catalog.services.books.covers.download", return_value=None)
    @mock.patch("catalog.services.lookup._get_json", return_value=None)
    def test_lookup_miss_creates_flagged_stub(self, *_):
        result = book_service.add_copy_by_isbn("9780306406157")
        self.assertTrue(result.book.needs_review)
        self.assertEqual(result.book.title, "ISBN 9780306406157")
        self.assertIsNotNone(result.copy)

    @mock.patch("catalog.services.books.covers.download", return_value=None)
    @mock.patch("catalog.services.lookup._get_json", return_value=None)
    def test_duplicate_requires_confirmation(self, *_):
        book_service.add_copy_by_isbn("9780306406157")
        second = book_service.add_copy_by_isbn("9780306406157")
        self.assertIsNone(second.copy)
        self.assertEqual(second.already_owned, 1)
        self.assertEqual(Copy.objects.count(), 1)

        third = book_service.add_copy_by_isbn("9780306406157", add_duplicate=True)
        self.assertIsNotNone(third.copy)
        self.assertEqual(Copy.objects.count(), 2)
        self.assertEqual(Book.objects.count(), 1)

    @mock.patch("catalog.services.books.covers.download")
    @mock.patch("catalog.services.lookup._get_json")
    def test_cover_is_downloaded_and_flagged(self, get_json, download):
        get_json.side_effect = [OL_PAYLOAD, None]
        download.return_value = png_bytes()
        result = book_service.add_copy_by_isbn("9780306406157")
        self.assertTrue(result.book.has_cover)
        self.assertTrue(covers.cover_path(result.book.pk).exists())
