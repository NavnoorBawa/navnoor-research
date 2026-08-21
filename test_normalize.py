"""Normalisation rules, including the two that protect honesty of display."""

from __future__ import annotations

import unittest

from navnoor_research import normalize


class TestAccess(unittest.TestCase):
    def test_free_audiences(self):
        for value in ("everyone", "public", "EVERYONE", " public "):
            self.assertEqual(normalize.access_of(value), normalize.ACCESS_FREE)

    def test_paid_audiences(self):
        for value in ("only_paid", "paid", "locked"):
            self.assertEqual(normalize.access_of(value), normalize.ACCESS_PAID)

    def test_unknown_is_not_guessed(self):
        for value in ("unknown", "", None, "something-new"):
            self.assertEqual(normalize.access_of(value), normalize.ACCESS_UNKNOWN)


class TestReadingMinutes(unittest.TestCase):
    def test_complete_body_is_trusted(self):
        self.assertEqual(normalize.reading_minutes(3332, "full"), 15)

    def test_excerpt_wordcount_is_refused(self):
        # An excerpt's wordcount describes the teaser, not the article. Printing
        # it would advertise a 3,000-word piece as a one-minute read.
        self.assertIsNone(normalize.reading_minutes(1819, "excerpt"))
        self.assertIsNone(normalize.reading_minutes(200, "registry"))

    def test_absent_or_zero(self):
        self.assertIsNone(normalize.reading_minutes(0, "full"))
        self.assertIsNone(normalize.reading_minutes(None, "full"))

    def test_never_rounds_down_to_zero(self):
        self.assertEqual(normalize.reading_minutes(5, "full"), 1)


class TestCleanText(unittest.TestCase):
    def test_strips_syndication_call_to_action(self):
        got = normalize.clean_text("The size tier absorbed it…\n\nContinue reading on Medium »")
        self.assertEqual(got, "The size tier absorbed it")

    def test_collapses_whitespace(self):
        self.assertEqual(normalize.clean_text("a  \n  b"), "a b")

    def test_empty(self):
        self.assertIsNone(normalize.clean_text("   "))
        self.assertIsNone(normalize.clean_text(None))


class TestSummaryRights(unittest.TestCase):
    """A body-derived lead may only describe a publicly readable article."""

    RECORD = {
        "subtitle": "A public subtitle.",
        "brief": {"lead": {"text": "A sentence lifted from the article body."}},
    }

    def test_free_article_may_use_the_lead(self):
        got = normalize.summary_for(self.RECORD, normalize.ACCESS_FREE)
        self.assertEqual(got, "A sentence lifted from the article body.")

    def test_paid_article_falls_back_to_the_subtitle(self):
        got = normalize.summary_for(self.RECORD, normalize.ACCESS_PAID)
        self.assertEqual(got, "A public subtitle.")

    def test_unknown_access_is_treated_as_paid(self):
        got = normalize.summary_for(self.RECORD, normalize.ACCESS_UNKNOWN)
        self.assertEqual(got, "A public subtitle.")

    def test_member_preview_is_never_read(self):
        record = {"member_preview": "members only text", "subtitle": None, "brief": None}
        self.assertIsNone(normalize.summary_for(record, normalize.ACCESS_PAID))

    def test_missing_brief_does_not_crash(self):
        self.assertIsNone(normalize.summary_for({"brief": None}, normalize.ACCESS_FREE))


class TestMisc(unittest.TestCase):
    def test_truncate_cuts_on_a_word_boundary(self):
        got = normalize.truncate("alpha beta gamma delta", 12)
        self.assertTrue(got.endswith("…"))
        self.assertLessEqual(len(got), 13)

    def test_truncate_leaves_short_text(self):
        self.assertEqual(normalize.truncate("short", 40), "short")

    def test_published_date(self):
        self.assertEqual(normalize.published_date("2026-08-20T13:31:31.862Z"), "2026-08-20")
        self.assertIsNone(normalize.published_date("not a date"))
        self.assertIsNone(normalize.published_date(None))

    def test_article_id_is_stable_and_scoped(self):
        self.assertEqual(normalize.article_id("substack", "A Slug!"), "substack:a-slug")
        self.assertEqual(normalize.article_id("medium", "a-slug"), "medium:a-slug")


if __name__ == "__main__":
    unittest.main()
