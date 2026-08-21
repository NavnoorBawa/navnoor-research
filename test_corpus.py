"""Corpus import: field projection, rejection rules, and rights containment."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from navnoor_research import corpus
from navnoor_research.config import Entity, Topic
from navnoor_research.entities import EntityMatcher, TopicClassifier

RECORD = {
    "source": "substack",
    "source_id": "a-post",
    "slug": "a-post",
    "title": "Citadel took the flows",
    "subtitle": "A public subtitle.",
    "post_date": "2026-08-20T13:31:31.862Z",
    "url": "https://navnoorbawa.substack.com/p/a-post",
    "audience": "everyone",
    "wordcount": 3332,
    "content_status": "full",
    "brief": {"lead": {"text": "A body sentence."}},
    # Fields the importer must never read:
    "member_preview": "MEMBERS ONLY TEXT",
    "body_text": "FULL BODY TEXT",
    "alternate_urls": ["https://example.com/x"],
}


class TestProjection(unittest.TestCase):
    def test_only_allowed_fields_survive(self):
        projected = corpus._project(RECORD)
        self.assertTrue(set(projected).issubset(corpus.ALLOWED_SOURCE_FIELDS))

    def test_prohibited_fields_are_excluded(self):
        projected = corpus._project(RECORD)
        for field in corpus.PROHIBITED_SOURCE_FIELDS:
            self.assertNotIn(field, projected)

    def test_allowed_and_prohibited_sets_do_not_overlap(self):
        overlap = corpus.ALLOWED_SOURCE_FIELDS & corpus.PROHIBITED_SOURCE_FIELDS
        self.assertEqual(overlap, frozenset())


class TestBuildArticle(unittest.TestCase):
    def setUp(self):
        self.matcher = EntityMatcher([Entity("citadel", "Citadel", "fund", [])])
        self.classifier = TopicClassifier([Topic("hedge-funds", "Hedge funds", [], ["citadel"])])

    def build(self, **overrides):
        record = dict(RECORD)
        record.update(overrides)
        return corpus.build_article(record, self.matcher, self.classifier)

    def test_happy_path(self):
        article = self.build()
        self.assertEqual(article.id, "substack:a-post")
        self.assertEqual(article.published, "2026-08-20")
        self.assertEqual(article.access, "free")
        self.assertEqual(article.topic, "hedge-funds")
        self.assertEqual(article.entities, ["citadel"])
        self.assertEqual(article.reading_minutes, 15)

    def test_member_text_never_reaches_the_output(self):
        article = self.build(audience="only_paid")
        serialised = json.dumps(article.to_json())
        self.assertNotIn("MEMBERS ONLY TEXT", serialised)
        self.assertNotIn("FULL BODY TEXT", serialised)
        self.assertNotIn("A body sentence.", serialised)
        self.assertEqual(article.summary, "A public subtitle.")

    def test_records_without_a_title_are_rejected(self):
        self.assertIsNone(self.build(title=""))

    def test_records_without_https_are_rejected(self):
        self.assertIsNone(self.build(url="http://example.com/x"))

    def test_records_without_a_date_are_rejected(self):
        self.assertIsNone(self.build(post_date=None))

    def test_excerpt_wordcount_does_not_become_a_reading_time(self):
        self.assertIsNone(self.build(content_status="excerpt").reading_minutes)


class TestLoadIndex(unittest.TestCase):
    def test_missing_corpus_raises_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(corpus.CorpusError) as ctx:
                corpus.load_index(Path(tmp))
            self.assertIn("CORPUS_DIR", str(ctx.exception))

    def test_non_list_corpus_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / corpus.CORPUS_INDEX_NAME).write_text("{}", encoding="utf-8")
            with self.assertRaises(corpus.CorpusError):
                corpus.load_index(Path(tmp))

    def test_import_is_deterministic_and_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            older = dict(RECORD, source_id="older", post_date="2025-01-01T00:00:00Z")
            (Path(tmp) / corpus.CORPUS_INDEX_NAME).write_text(
                json.dumps([older, RECORD]), encoding="utf-8")
            first, stats = corpus.import_articles(Path(tmp))
            second, _ = corpus.import_articles(Path(tmp))
            self.assertEqual([a.id for a in first], ["substack:a-post", "substack:older"])
            self.assertEqual([a.to_json() for a in first], [a.to_json() for a in second])
            self.assertEqual(stats["published"], 2)


if __name__ == "__main__":
    unittest.main()
