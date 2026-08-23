"""Independent data-contract tests for the exact tracked publication inputs."""

from __future__ import annotations

import copy
import json
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import validate_data
from navnoor_research import config, jsonio, newsstore, paths, seed
from navnoor_research.entities import TopicClassifier

ROOT = Path(__file__).resolve().parent
NOMURA_ID = "r_43cbaba52334415bfd48774594ee2e9fdfce29d7a908b799b44a1ceb8a10b522"


class TestTrackedDataContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = config.load_sources()
        cls.entity_ids = {entity.id for entity in config.load_entities()}
        cls.topic_ids = set(TopicClassifier(config.load_topics()).order())
        cls.research = jsonio.load(paths.RESEARCH_PATH)
        cls.news = jsonio.load(paths.NEWS_PATH)

    def assert_research_rejected(self, mutate) -> None:
        document = copy.deepcopy(self.research)
        mutate(document)
        with self.assertRaises(validate_data.ValidationError):
            validate_data.validate_research(document, self.entity_ids, self.topic_ids)

    def test_full_fixed_path_validation_succeeds(self):
        research, companies, news = validate_data.load_and_validate()
        seeded = jsonio.load(paths.PUBLICATIONS_PATH)["records"]
        self.assertEqual(len(research["research"]), len(seeded))
        self.assertGreaterEqual(len(companies["items"]), 10_000)
        self.assertLessEqual(len(news["items"]), newsstore.MAX_ITEMS)
        validate_data.validate_source_matrix(self.sources)

    def test_research_rejects_forbidden_missing_duplicate_future_and_wrong_host(self):
        self.assert_research_rejected(
            lambda document: document["research"][0].__setitem__("body_text", "not metadata")
        )
        self.assert_research_rejected(lambda document: document["research"][0].pop("title"))
        self.assert_research_rejected(
            lambda document: document["research"].append(copy.deepcopy(document["research"][0]))
        )
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assert_research_rejected(
            lambda document: document["research"][0].__setitem__("published", future)
        )
        self.assert_research_rejected(
            lambda document: document["research"][0].__setitem__(
                "url", "https://www.federalreserve.gov/not-the-publication"
            )
        )

    def test_restricted_nomura_record_is_only_reviewed_publication_metadata(self):
        seed_document = jsonio.load(paths.PUBLICATIONS_PATH)
        seeded = next(record for record in seed_document["records"] if record["id"] == NOMURA_ID)
        public = next(record for record in self.research["research"] if record["id"] == NOMURA_ID)
        self.assertEqual(public["access"], "restricted")
        self.assertEqual(public.get("summary"), seeded["subtitle"])
        self.assertTrue(validate_data.RESEARCH_REQUIRED.issubset(public))
        self.assertTrue(set(public).issubset(validate_data.RESEARCH_FIELDS))
        self.assertFalse(set(public) & validate_data.FORBIDDEN_FIELDS)
        for forbidden in ("reading_minutes", "body_text", "member_preview", "wordcount"):
            self.assertNotIn(forbidden, seeded)

    def test_seed_projection_contains_only_reviewed_fields(self):
        document = jsonio.load(paths.PUBLICATIONS_PATH)
        self.assertEqual(document["rights_profile"], seed.RIGHTS_PROFILE)
        self.assertEqual(
            len(document["records"]),
            jsonio.load(paths.SEED_MANIFEST_PATH)["counts"]["records"],
        )
        for record in document["records"]:
            self.assertEqual(set(record), seed.RECORD_KEYS)
            self.assertFalse(set(record) & validate_data.FORBIDDEN_FIELDS)

    def test_news_has_canonical_publishers_and_consistent_source_counts(self):
        counts = Counter(item["source_id"] for item in self.news["items"])
        for item in self.news["items"]:
            self.assertTrue(newsstore.headline_allowed(item["title"]))
            self.assertEqual(item["publisher"], (urlsplit(item["url"]).hostname or "").lower())
        for source_id, state in self.news["sources"].items():
            self.assertEqual(state["item_count"], counts[source_id])

    def test_legacy_rights_unsafe_import_paths_are_absent(self):
        self.assertFalse((ROOT / "data" / "articles.json").exists())
        self.assertFalse((ROOT / "import_articles.py").exists())
        source = json.dumps(jsonio.load(paths.PUBLICATIONS_PATH), ensure_ascii=False)
        for forbidden in ('"body_text"', '"member_preview"', '"reading_minutes"'):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
