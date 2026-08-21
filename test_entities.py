"""Entity matching precision and topic assignment."""

from __future__ import annotations

import unittest

from navnoor_research import config
from navnoor_research.config import Entity, Topic
from navnoor_research.entities import EntityMatcher, TopicClassifier


class TestEntityMatcher(unittest.TestCase):
    def setUp(self):
        self.matcher = EntityMatcher([
            Entity("bp", "BP plc", "ticker", ["BP"]),
            Entity("sec", "U.S. Securities and Exchange Commission", "regulator", ["SEC"]),
            Entity("spx", "S&P 500", "index", ["SPX", "SPY"]),
            Entity("ltcm", "Long-Term Capital Management", "fund", ["LTCM"]),
            Entity("de-shaw", "D. E. Shaw", "fund", ["DE Shaw", "D.E. Shaw"]),
            Entity("crowding", "Crowding", "concept", ["crowded trade"]),
        ])

    def test_short_uppercase_alias_is_case_sensitive(self):
        self.assertIn("bp", self.matcher.find("BP reported earnings"))
        # Lowercase 'bp' is prose, not the ticker.
        self.assertNotIn("bp", self.matcher.find("the bp of the matter"))

    def test_acronym_does_not_match_inside_a_word(self):
        self.assertNotIn("sec", self.matcher.find("a second look at the sector"))
        self.assertIn("sec", self.matcher.find("The SEC filed charges"))

    def test_punctuated_surface_forms(self):
        self.assertIn("spx", self.matcher.find("The S&P 500 closed lower"))
        self.assertIn("de-shaw", self.matcher.find("D.E. Shaw hired a team"))

    def test_flexible_whitespace(self):
        self.assertIn("ltcm", self.matcher.find("Long-Term  Capital\nManagement collapsed"))

    def test_multiword_case_insensitive(self):
        self.assertIn("crowding", self.matcher.find("a crowded trade unwound"))

    def test_empty_text(self):
        self.assertEqual(self.matcher.find(""), [])

    def test_order_follows_configuration(self):
        found = self.matcher.find("BP and the SEC and the S&P 500")
        self.assertEqual(found, ["bp", "sec", "spx"])


class TestTopicClassifier(unittest.TestCase):
    def setUp(self):
        self.classifier = TopicClassifier([
            Topic("volatility", "Volatility", ["volatility", "options"], ["vix"]),
            Topic("regulation", "Regulation", ["enforcement", "charged"], ["sec"]),
        ])

    def test_entity_evidence_wins(self):
        self.assertEqual(self.classifier.classify("The SEC charged a firm", ["sec"]), "regulation")

    def test_keyword_only(self):
        self.assertEqual(self.classifier.classify("implied volatility rose", []), "volatility")

    def test_fallback_when_nothing_matches(self):
        self.assertEqual(self.classifier.classify("a quiet morning", []), "general")

    def test_labels_include_the_fallback(self):
        self.assertEqual(self.classifier.labels()["general"], "General")

    def test_ties_break_on_configuration_order(self):
        # One keyword each; the earlier topic must win.
        self.assertEqual(self.classifier.classify("options and enforcement", []), "volatility")


class TestShippedConfiguration(unittest.TestCase):
    """The real tables must load and behave."""

    def test_real_tables_classify_a_known_headline(self):
        matcher = EntityMatcher(config.load_entities())
        classifier = TopicClassifier(config.load_topics())
        text = "Citadel and Millennium's size tier took $6.5 billion anyway"
        found = matcher.find(text)
        self.assertIn("citadel", found)
        self.assertIn("millennium", found)
        self.assertEqual(classifier.classify(text, found), "hedge-funds")

    def test_every_topic_entity_reference_resolves(self):
        known = {e.id for e in config.load_entities()}
        for topic in config.load_topics():
            for entity_id in topic.entities:
                self.assertIn(entity_id, known, f"{topic.id} references {entity_id}")


if __name__ == "__main__":
    unittest.main()
