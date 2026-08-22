"""Metadata-only research derivation from the committed seed transaction."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from navnoor_research import corpus, paths, seed
from navnoor_research.config import Entity, Topic
from navnoor_research.entities import EntityMatcher, TopicClassifier


def record(**overrides):
    value = {
        "access": "public",
        "alternate_urls": {},
        "canonical_url": "https://navnoorbawa.substack.com/p/citadel-flows",
        "id": seed.publication_id("substack", "citadel-flows"),
        "published_at": "2026-08-20T13:31:31.862Z",
        "slug": "citadel-flows",
        "source": "substack",
        "source_id": "citadel-flows",
        "subtitle": "A public subtitle about Citadel order flow.",
        "title": "Citadel took the flows",
    }
    value.update(overrides)
    return value


class TestRecordDerivation(unittest.TestCase):
    def setUp(self):
        self.matcher = EntityMatcher([
            Entity("citadel", "Citadel", "fund", ["Ken Griffin"])
        ])
        self.classifier = TopicClassifier([
            Topic("hedge-funds", "Hedge funds", ["order flow"], ["citadel"])
        ])

    def test_source_projection_sets_are_closed_and_disjoint(self):
        self.assertEqual(corpus.ALLOWED_SOURCE_FIELDS, seed.RECORD_KEYS)
        self.assertFalse(
            corpus.ALLOWED_SOURCE_FIELDS & corpus.PROHIBITED_SOURCE_FIELDS
        )

    def test_build_article_uses_only_title_subtitle_link_and_metadata(self):
        built = corpus.build_article(record(), self.matcher, self.classifier)
        self.assertEqual(built.id, seed.publication_id("substack", "citadel-flows"))
        self.assertEqual(built.published, "2026-08-20T13:31:31.862Z")
        self.assertEqual(built.access, "public")
        self.assertEqual(built.entities, ["citadel"])
        self.assertEqual(built.topic, "hedge-funds")
        self.assertEqual(built.summary, "A public subtitle about Citadel order flow.")
        self.assertEqual(
            set(built.to_json()),
            {"access", "entities", "id", "published", "source", "summary",
             "title", "topic", "url"},
        )
        self.assertFalse(hasattr(built, "reading_minutes"))

    def test_extra_body_trade_or_derived_fields_fail_closed(self):
        for field in corpus.PROHIBITED_SOURCE_FIELDS:
            changed = record(**{field: "DO_NOT_PUBLISH"})
            with self.subTest(field=field), self.assertRaises(corpus.CorpusError):
                corpus.build_article(changed, self.matcher, self.classifier)

    def test_missing_title_https_url_or_publication_time_is_refused(self):
        changes = (
            {"title": ""},
            {"canonical_url": "http://navnoorbawa.substack.com/p/citadel-flows"},
            {"published_at": ""},
            {"access": "free"},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(corpus.CorpusError):
                corpus.build_article(record(**change), self.matcher, self.classifier)


class TestSeedTransactionLoading(unittest.TestCase):
    def setUp(self):
        self.publication_bytes = paths.PUBLICATIONS_PATH.read_bytes()
        self.manifest_bytes = paths.SEED_MANIFEST_PATH.read_bytes()

    def patch_paths(self, directory):
        publication_path = Path(directory) / "publications.json"
        manifest_path = Path(directory) / "manifest.json"
        return (
            publication_path,
            manifest_path,
            mock.patch.object(paths, "PUBLICATIONS_PATH", publication_path),
            mock.patch.object(paths, "SEED_MANIFEST_PATH", manifest_path),
        )

    def test_both_seed_files_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            publication, _manifest, pub_patch, manifest_patch = self.patch_paths(
                temporary
            )
            publication.write_bytes(self.publication_bytes)
            with pub_patch, manifest_patch:
                with self.assertRaises(corpus.CorpusError) as caught:
                    corpus.load_index()
        self.assertIn("transaction is incomplete", str(caught.exception))

    def test_manifest_is_a_byte_exact_commit_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            publication, manifest, pub_patch, manifest_patch = self.patch_paths(
                temporary
            )
            publication.write_bytes(self.publication_bytes + b" ")
            manifest.write_bytes(self.manifest_bytes)
            with pub_patch, manifest_patch:
                with self.assertRaises(corpus.CorpusError) as caught:
                    corpus.load_index()
        self.assertIn("exact publication bytes", str(caught.exception))

    def test_duplicate_key_seed_is_refused_before_derivation(self):
        with tempfile.TemporaryDirectory() as temporary:
            publication, manifest, pub_patch, manifest_patch = self.patch_paths(
                temporary
            )
            publication.write_bytes(b'{"schema_version":1,"schema_version":1}')
            manifest.write_bytes(self.manifest_bytes)
            with pub_patch, manifest_patch:
                with self.assertRaises(corpus.CorpusError):
                    corpus.load_index()

    def test_exact_committed_pair_round_trips(self):
        with tempfile.TemporaryDirectory() as temporary:
            publication, manifest, pub_patch, manifest_patch = self.patch_paths(
                temporary
            )
            publication.write_bytes(self.publication_bytes)
            manifest.write_bytes(self.manifest_bytes)
            with pub_patch, manifest_patch:
                records, document, provenance = corpus.load_index()
        self.assertEqual(len(records), 568)
        self.assertEqual(records, document["records"])
        self.assertEqual(provenance["counts"]["records"], 568)


class TestCurrentCorpus(unittest.TestCase):
    NOMURA_TITLE = (
        "A Nomura Trader Made $10,284 Spoofing ¥400 Billion in JGB Orders. "
        "BlueCrest Hired Him for the Alpha Inside."
    )
    NOMURA_SUBTITLE = (
        "The talent arbitrage, the surveillance blind spot Nomura admitted in "
        "writing, and the post-YCC JGB steepener thesis behind Michael Platt's "
        "most counterintuitive hire"
    )
    NOMURA_BODY_LEAD = "spent five hours manufacturing order book pressure"

    def test_current_seed_is_exactly_568_metadata_records(self):
        records, document, provenance = corpus.load_index()
        self.assertEqual(len(records), 568)
        self.assertEqual(provenance["counts"]["records"], 568)
        self.assertEqual(
            provenance["source_snapshot"]["catalog_count"],
            568,
        )
        self.assertRegex(document["source_dataset_version"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            provenance["source_snapshot"]["revision"],
            r"^[0-9a-f]{40}$",
        )
        self.assertTrue(all(set(row) == seed.RECORD_KEYS for row in records))
        encoded = json.dumps(records, ensure_ascii=False)
        for field in corpus.PROHIBITED_SOURCE_FIELDS:
            self.assertNotIn(f'"{field}"', encoded)

    def test_restricted_nomura_record_uses_subtitle_not_body_lead(self):
        articles, _stats = corpus.import_articles()
        matches = [article for article in articles if article.title == self.NOMURA_TITLE]
        self.assertEqual(len(matches), 1)
        article = matches[0]
        self.assertEqual(article.access, "restricted")
        self.assertEqual(article.summary, self.NOMURA_SUBTITLE)
        serialized = json.dumps(article.to_json(), ensure_ascii=False)
        self.assertNotIn(self.NOMURA_BODY_LEAD, serialized)
        self.assertNotIn("member_preview", serialized)
        self.assertNotIn("reading_minutes", serialized)
        self.assertFalse(hasattr(article, "reading_minutes"))

    def test_import_is_deterministic_newest_first_and_metadata_only(self):
        first, stats = corpus.import_articles()
        second, second_stats = corpus.import_articles()
        self.assertEqual(len(first), 568)
        self.assertEqual(stats, second_stats)
        self.assertEqual(
            [article.to_json() for article in first],
            [article.to_json() for article in second],
        )
        keys = {
            "access", "entities", "id", "published", "source", "summary",
            "title", "topic", "url",
        }
        for article in first:
            self.assertTrue(set(article.to_json()).issubset(keys))
        expected = sorted(
            first,
            key=lambda article: (article.published, article.id),
            reverse=True,
        )
        self.assertEqual(first, expected)
        self.assertEqual(stats["read"], 568)
        self.assertEqual(stats["published"], 568)


if __name__ == "__main__":
    unittest.main()
