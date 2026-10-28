from django.test import SimpleTestCase

from catalog.services import isbn
from catalog.services.sortkeys import author_sort_key, fold, title_sort_key


class IsbnTests(SimpleTestCase):
    def test_normalizes_isbn10_to_isbn13(self):
        self.assertEqual(isbn.normalize("0-306-40615-2"), "9780306406157")

    def test_accepts_isbn13_with_hyphens_and_prefix(self):
        self.assertEqual(isbn.normalize("ISBN 978-0-306-40615-7"), "9780306406157")

    def test_isbn10_with_x_check_digit(self):
        self.assertEqual(isbn.normalize("080442957X"), "9780804429573")

    def test_rejects_bad_checksum(self):
        self.assertIsNone(isbn.normalize("9780306406158"))
        self.assertIsNone(isbn.normalize("0306406153"))

    def test_rejects_garbage(self):
        self.assertIsNone(isbn.normalize(""))
        self.assertIsNone(isbn.normalize("hello"))

    def test_to_10_only_for_978(self):
        self.assertEqual(isbn.to_10("9780306406157"), "0306406152")
        self.assertIsNone(isbn.to_10("9791032305690"))


class SortKeyTests(SimpleTestCase):
    def test_title_drops_leading_article(self):
        self.assertEqual(title_sort_key("The Brothers Karamazov"), "brothers karamazov")
        self.assertEqual(title_sort_key("A Tale of Two Cities"), "tale of two cities")
        self.assertEqual(title_sort_key("Theory of Games"), "theory of games")

    def test_title_that_is_only_an_article_is_kept(self):
        self.assertEqual(title_sort_key("The"), "the")

    def test_fold_handles_accents_and_cyrillic(self):
        self.assertEqual(fold("Café Müller"), "cafe muller")
        self.assertEqual(fold("ВОЙНА и Мир"), fold("война И мир"))

    def test_author_sort_simple(self):
        self.assertEqual(author_sort_key("Fyodor Dostoevsky"), "dostoevsky fyodor")

    def test_author_sort_with_particle(self):
        self.assertEqual(author_sort_key("Ludwig van Beethoven"), "van beethoven ludwig")

    def test_author_sort_already_inverted(self):
        self.assertEqual(author_sort_key("Tolstoy, Leo"), "tolstoy leo")

    def test_author_sort_suffix(self):
        self.assertEqual(author_sort_key("Martin Luther King Jr."), "king martin luther")

    def test_author_sort_uses_first_author_only(self):
        self.assertEqual(author_sort_key("Adam Smith; David Hume"), "smith adam")

    def test_author_sort_single_name_and_empty(self):
        self.assertEqual(author_sort_key("Plato"), "plato")
        self.assertEqual(author_sort_key(""), "")
