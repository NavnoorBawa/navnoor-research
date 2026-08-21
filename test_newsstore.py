"""Headline store: identity, retention, merge order, and atomic promotion."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from navnoor_research import newsstore
from navnoor_research.config import Source
from navnoor_research.entities import EntityMatcher, TopicClassifier
from navnoor_research.models import NewsItem

SOURCE = Source(
    id="federal-reserve-rss", label="Federal Reserve Board", status="enabled",
    allowed_hosts=["www.federalreserve.gov"], allowed_fields=[], prohibited_fields=[],
    attribution="Federal Reserve Board", poll_interval_seconds=3600, retention_days=365,
)

NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


def item(id_, published, source_id="federal-reserve-rss"):
    return {"id": id_, "title": "t", "url": "https://x/", "source_id": source_id,
            "attribution": "a", "published": published, "entities": [], "topic": "general"}


class TestIdentity(unittest.TestCase):
    def test_id_is_stable_for_a_url(self):
        self.assertEqual(newsstore.news_id("https://a/"), newsstore.news_id("https://a/"))

    def test_id_differs_between_urls(self):
        self.assertNotEqual(newsstore.news_id("https://a/"), newsstore.news_id("https://b/"))


class TestBuildItem(unittest.TestCase):
    def setUp(self):
        self.matcher = EntityMatcher([])
        self.classifier = TopicClassifier([])

    def test_requires_title_url_and_date(self):
        for raw in ({"title": "", "url": "https://a/", "published_at": "2026-01-01T00:00:00Z"},
                    {"title": "t", "url": "http://a/", "published_at": "2026-01-01T00:00:00Z"},
                    {"title": "t", "url": "https://a/"}):
            self.assertIsNone(newsstore.build_item(raw, SOURCE, self.matcher, self.classifier))

    def test_seen_at_is_accepted_when_no_published_at(self):
        built = newsstore.build_item(
            {"title": "t", "url": "https://a/", "seen_at": "2026-08-21T08:30:00Z"},
            SOURCE, self.matcher, self.classifier)
        self.assertIsNotNone(built)
        self.assertEqual(built.published, "2026-08-21T08:30:00Z")
        self.assertEqual(built.attribution, "Federal Reserve Board")


class TestMerge(unittest.TestCase):
    def test_incoming_replaces_stored_record(self):
        previous = [item("a", "2026-08-01T00:00:00Z")]
        fresh = NewsItem(id="a", title="corrected", url="https://x/",
                         source_id="federal-reserve-rss", attribution="a",
                         published="2026-08-02T00:00:00Z")
        merged = newsstore.merge(previous, [fresh], {"federal-reserve-rss": 365}, NOW)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "corrected")

    def test_retention_drops_stale_records(self):
        previous = [item("old", "2024-01-01T00:00:00Z"), item("new", "2026-08-20T00:00:00Z")]
        merged = newsstore.merge(previous, [], {"federal-reserve-rss": 365}, NOW)
        self.assertEqual([r["id"] for r in merged], ["new"])

    def test_zero_retention_keeps_everything(self):
        previous = [item("old", "2020-01-01T00:00:00Z")]
        merged = newsstore.merge(previous, [], {"federal-reserve-rss": 0}, NOW)
        self.assertEqual(len(merged), 1)

    def test_newest_first(self):
        previous = [item("a", "2026-08-01T00:00:00Z"), item("b", "2026-08-19T00:00:00Z")]
        merged = newsstore.merge(previous, [], {}, NOW)
        self.assertEqual([r["id"] for r in merged], ["b", "a"])

    def test_bounded_length(self):
        previous = [item(str(n), "2026-08-19T00:00:00Z") for n in range(newsstore.MAX_ITEMS + 50)]
        merged = newsstore.merge(previous, [], {}, NOW)
        self.assertEqual(len(merged), newsstore.MAX_ITEMS)


class TestPromotion(unittest.TestCase):
    def test_promote_writes_a_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "news.json"
            newsstore.promote([item("a", "2026-08-20T00:00:00Z")], "2026-08-21T00:00:00Z", target)
            loaded = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(loaded["checked_at"], "2026-08-21T00:00:00Z")
            self.assertEqual(len(loaded["items"]), 1)

    def test_previous_snapshot_survives_a_failed_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "news.json"
            newsstore.promote([item("good", "2026-08-20T00:00:00Z")],
                              "2026-08-21T00:00:00Z", target)
            before = target.read_text(encoding="utf-8")

            class Boom(Exception):
                pass

            unserialisable = [{"id": "x", "bad": {1, 2}}]
            with self.assertRaises(TypeError):
                newsstore.promote(unserialisable, "2026-08-22T00:00:00Z", target)
            self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_load_returns_empty_snapshot_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = newsstore.load(Path(tmp) / "missing.json")
            self.assertEqual(snapshot["items"], [])
            self.assertIsNone(snapshot["checked_at"])


if __name__ == "__main__":
    unittest.main()
