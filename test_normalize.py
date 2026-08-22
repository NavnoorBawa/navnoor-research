"""Deterministic helpers used only on public publication metadata."""

from __future__ import annotations

import unittest

from navnoor_research import normalize


class TestCleanText(unittest.TestCase):
    def test_strips_syndication_call_to_action_and_dangling_ellipsis(self):
        value = "The size tier absorbed it…\n\nContinue reading on Medium »"
        self.assertEqual(normalize.clean_text(value), "The size tier absorbed it")

    def test_collapses_all_runs_of_whitespace(self):
        self.assertEqual(normalize.clean_text("  alpha \n\t beta   gamma  "),
                         "alpha beta gamma")

    def test_empty_values_stay_absent(self):
        self.assertIsNone(normalize.clean_text("   \n\t "))
        self.assertIsNone(normalize.clean_text(None))

    def test_ordinary_public_subtitle_is_not_rewritten(self):
        subtitle = "Liquidity, order flow, and a market-structure post-mortem."
        self.assertEqual(normalize.clean_text(subtitle), subtitle)


class TestTruncate(unittest.TestCase):
    def test_cuts_on_a_word_boundary_and_marks_the_cut(self):
        result = normalize.truncate("alpha beta gamma delta", 12)
        self.assertEqual(result, "alpha beta…")

    def test_short_text_is_byte_for_byte_unchanged(self):
        self.assertEqual(normalize.truncate("short", 40), "short")

    def test_long_single_token_remains_bounded(self):
        result = normalize.truncate("x" * 100, 12)
        self.assertEqual(result, "x" * 12 + "…")
        self.assertEqual(len(result), 13)

    def test_trailing_punctuation_is_not_left_before_ellipsis(self):
        result = normalize.truncate("alpha beta, gamma delta", 12)
        self.assertFalse(result.endswith(",…"))
        self.assertTrue(result.endswith("…"))


class TestPublishedDate(unittest.TestCase):
    def test_extracts_date_from_reviewed_date_and_utc_instant_shapes(self):
        self.assertEqual(normalize.published_date("2026-08-20"), "2026-08-20")
        self.assertEqual(
            normalize.published_date("2026-08-20T13:31:31.862Z"),
            "2026-08-20",
        )

    def test_missing_or_unshaped_values_stay_absent(self):
        for value in (None, "", "not a date", "20-08-2026", "2026-8-20"):
            with self.subTest(value=value):
                self.assertIsNone(normalize.published_date(value))


class TestMetadataConstants(unittest.TestCase):
    def test_access_states_match_the_seed_contract(self):
        self.assertEqual(
            {
                normalize.ACCESS_PUBLIC,
                normalize.ACCESS_RESTRICTED,
                normalize.ACCESS_UNKNOWN,
            },
            {"public", "restricted", "unknown"},
        )

    def test_every_reviewed_archive_source_has_a_stable_display_label(self):
        self.assertEqual(
            normalize.SOURCE_LABELS,
            {
                "substack": "Substack",
                "medium": "Medium",
                "patreon": "Patreon",
                "fxempire": "FXEmpire",
            },
        )


if __name__ == "__main__":
    unittest.main()
