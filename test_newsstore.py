"""Schema-3 checked-headline storage, policy, retention, and LKG safety."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from navnoor_research import jsonio, newsstore
from navnoor_research.adapters import gdelt, rss
from navnoor_research.config import Entity, Source, Topic
from navnoor_research.entities import EntityMatcher, TopicClassifier
from navnoor_research.models import NewsItem

RSS_SOURCE = Source(
    id="federal-reserve-rss",
    label="Federal Reserve Board",
    status="enabled",
    adapter="rss",
    allowed_hosts=["www.federalreserve.gov"],
    link_hosts=["www.federalreserve.gov"],
    allowed_fields=sorted(rss.ALLOWED_FIELDS),
    prohibited_fields=["body", "image", "attachment"],
    attribution="Federal Reserve Board",
    poll_interval_seconds=3_600,
    retention_days=365,
)
GDELT_SOURCE = Source(
    id="gdelt-doc-v2",
    label="GDELT Project",
    status="enabled",
    adapter="gdelt",
    allowed_hosts=["api.gdeltproject.org"],
    link_hosts=[],
    allowed_fields=sorted(gdelt.ALLOWED_FIELDS),
    prohibited_fields=["body", "snippet", "image", "tone"],
    attribution="Discovery metadata: GDELT Project",
    poll_interval_seconds=3_600,
    retention_days=90,
)
DISABLED_SOURCE = Source(
    id="cftc-rss",
    label="CFTC",
    status="disabled",
    adapter="rss",
    allowed_hosts=["www.cftc.gov"],
    link_hosts=["www.cftc.gov"],
    allowed_fields=sorted(rss.ALLOWED_FIELDS),
    prohibited_fields=[],
    attribution="CFTC",
    poll_interval_seconds=3_600,
    retention_days=365,
)
SOURCES = {
    source.id: source for source in (RSS_SOURCE, GDELT_SOURCE, DISABLED_SOURCE)
}
ENTITY_IDS = {"federal-reserve"}
TOPIC_IDS = {"general", "rates-macro"}
NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-08-21T12:00:00Z"


def item_record(
    *,
    url="https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
    title="Federal Reserve issues a policy statement",
    published="2026-08-20T14:00:00Z",
    source=RSS_SOURCE,
    entities=None,
    topic="rates-macro",
):
    return {
        "attribution": source.attribution,
        "entities": list(entities or []),
        "id": newsstore.news_id(url),
        "published": published,
        "publisher": (url.split("/", 3)[2]).lower(),
        "source_id": source.id,
        "title": title,
        "topic": topic,
        "url": url,
    }


def valid_snapshot(items=None):
    records = list(items or [])
    snapshot = newsstore.empty_snapshot(SOURCES)
    snapshot["items"] = sorted(
        records,
        key=lambda record: (record["published"], record["id"]),
        reverse=True,
    )
    used = {record["source_id"] for record in records}
    for source_id in used:
        snapshot["sources"][source_id].update({
            "last_attempt_at": NOW_ISO,
            "last_success_at": NOW_ISO,
            "status": "ok",
        })
    return newsstore.with_item_counts(snapshot)


class TestIdentityAndProjection(unittest.TestCase):
    def setUp(self):
        self.matcher = EntityMatcher([
            Entity("federal-reserve", "Federal Reserve", "regulator", ["FOMC"])
        ])
        self.classifier = TopicClassifier([
            Topic("rates-macro", "Rates", ["policy statement"], ["federal-reserve"])
        ])

    def raw_rss(self, **overrides):
        row = {
            "guid": "fed-1",
            "title": "Federal Reserve issues a policy statement",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/a.htm",
            "published_at": "2026-08-20T14:00:00Z",
            "summary": "Checked description metadata.",
            "category": "Monetary Policy",
        }
        row.update(overrides)
        return row

    def test_identity_is_full_stable_and_url_scoped(self):
        first = newsstore.news_id("https://example.com/a")
        self.assertEqual(first, newsstore.news_id("https://example.com/a"))
        self.assertNotEqual(first, newsstore.news_id("https://example.com/b"))
        self.assertTrue(first.startswith("n_"))
        self.assertEqual(len(first), 66)

    def test_build_item_projects_publisher_and_source_attribution(self):
        built = newsstore.build_item(
            self.raw_rss(), RSS_SOURCE, self.matcher, self.classifier, now=NOW
        )
        self.assertIsNotNone(built)
        assert built is not None
        self.assertEqual(built.publisher, "www.federalreserve.gov")
        self.assertEqual(built.attribution, "Federal Reserve Board")
        self.assertEqual(built.entities, ["federal-reserve"])
        self.assertEqual(built.topic, "rates-macro")
        self.assertEqual(set(built.to_json()), newsstore.ITEM_FIELDS)

    def test_gdelt_publisher_is_the_canonical_url_host_not_a_brand_guess(self):
        raw = {
            "title": "Treasury yields move after policy decision",
            "url": "https://News.Example.com/markets/a",
            "domain": "news.example.com",
            "seen_at": "2026-08-20T14:00:00Z",
            "language": "English",
            "source_country": "United States",
        }
        built = newsstore.build_item(
            raw, GDELT_SOURCE, self.matcher, self.classifier, now=NOW
        )
        self.assertIsNotNone(built)
        assert built is not None
        self.assertEqual(built.publisher, "news.example.com")
        self.assertEqual(built.attribution, "Discovery metadata: GDELT Project")

        raw["domain"] = "declared.example"
        with self.assertRaises(newsstore.NewsError):
            newsstore.build_item(
                raw, GDELT_SOURCE, self.matcher, self.classifier, now=NOW
            )

    def test_adapter_fields_are_fail_closed_against_unknown_or_prohibited_data(self):
        for field in ("body", "unexpected"):
            with self.subTest(field=field), self.assertRaises(newsstore.NewsError):
                newsstore.build_item(
                    self.raw_rss(**{field: "must not pass"}),
                    RSS_SOURCE,
                    self.matcher,
                    self.classifier,
                    now=NOW,
                )

    def test_missing_or_off_host_metadata_is_refused(self):
        invalid = (
            self.raw_rss(title=""),
            self.raw_rss(url="http://www.federalreserve.gov/a"),
            self.raw_rss(url="https://evil.example/a"),
            self.raw_rss(published_at=""),
        )
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(newsstore.NewsError):
                newsstore.build_item(
                    row, RSS_SOURCE, self.matcher, self.classifier, now=NOW
                )

    def test_future_timestamp_is_refused(self):
        with self.assertRaises(newsstore.NewsError) as caught:
            newsstore.build_item(
                self.raw_rss(published_at="2026-08-21T12:05:01Z"),
                RSS_SOURCE,
                self.matcher,
                self.classifier,
                now=NOW,
            )
        self.assertIn("future", str(caught.exception))

    def test_live_target_rating_and_recommendation_headlines_are_filtered(self):
        banned = (
            "Markets LIVE updates as stocks fall",
            "Broker raises the price target on Nvidia",
            "Analyst reiterates Strong Buy rating",
            "Bank upgraded Acme to Buy",
            "Goldman downgrades Acme",
            "Analyst cuts Nvidia target to $100",
            "Wall Street says Nvidia is a buy",
            "Top stock picks for 2026",
            "Acme upgraded after earnings",
            "Three stocks to buy this week",
            "A portfolio recommendation for volatile markets",
        )
        for title in banned:
            with self.subTest(title=title):
                self.assertIsNone(newsstore.build_item(
                    self.raw_rss(title=title),
                    RSS_SOURCE,
                    self.matcher,
                    self.classifier,
                    now=NOW,
                ))


class TestSchemaThreeSnapshot(unittest.TestCase):
    def test_empty_snapshot_has_per_source_state_only_for_enabled_news_adapters(self):
        snapshot = newsstore.empty_snapshot(SOURCES)
        self.assertEqual(snapshot["schema_version"], 3)
        self.assertEqual(set(snapshot), newsstore.SNAPSHOT_FIELDS)
        self.assertEqual(
            set(snapshot["sources"]),
            {RSS_SOURCE.id, GDELT_SOURCE.id},
        )
        for state in snapshot["sources"].values():
            self.assertEqual(set(state), newsstore.STATE_FIELDS)
            self.assertEqual(state["status"], "never")
            self.assertIsNone(state["last_attempt_at"])
            self.assertIsNone(state["last_success_at"])

    def test_valid_snapshot_has_exact_item_and_source_state_contracts(self):
        document = valid_snapshot([item_record(entities=["federal-reserve"])])
        checked = newsstore.validate_snapshot(
            document, SOURCES, ENTITY_IDS, TOPIC_IDS, now=NOW
        )
        self.assertEqual(checked, document)
        self.assertEqual(checked["sources"][RSS_SOURCE.id]["item_count"], 1)
        self.assertEqual(checked["sources"][GDELT_SOURCE.id]["status"], "never")

    def test_partial_state_is_visible_without_overstating_a_success(self):
        document = valid_snapshot()
        document["sources"][GDELT_SOURCE.id].update({
            "last_attempt_at": NOW_ISO,
            "last_success_at": None,
            "status": "partial",
        })
        checked = newsstore.validate_snapshot(
            document, SOURCES, ENTITY_IDS, TOPIC_IDS, now=NOW
        )
        self.assertEqual(checked["sources"][GDELT_SOURCE.id]["status"], "partial")
        self.assertIsNone(checked["sources"][GDELT_SOURCE.id]["last_success_at"])

    def test_source_state_count_attribution_and_timestamps_are_cross_checked(self):
        base = valid_snapshot([item_record()])
        mutations = []

        changed = deepcopy(base)
        changed["sources"][RSS_SOURCE.id]["item_count"] = 0
        mutations.append(changed)

        changed = deepcopy(base)
        changed["sources"][RSS_SOURCE.id]["attribution"] = "Publisher guessed"
        mutations.append(changed)

        changed = deepcopy(base)
        changed["sources"][RSS_SOURCE.id]["last_success_at"] = (
            "2026-08-21T11:59:59Z"
        )
        mutations.append(changed)

        changed = deepcopy(base)
        changed["sources"][GDELT_SOURCE.id]["last_attempt_at"] = NOW_ISO
        mutations.append(changed)

        changed = deepcopy(base)
        changed["sources"][GDELT_SOURCE.id]["status"] = "unknown"
        mutations.append(changed)

        changed = deepcopy(base)
        changed["sources"][GDELT_SOURCE.id]["status"] = "error"
        changed["sources"][GDELT_SOURCE.id]["last_attempt_at"] = (
            "2026-08-21T12:05:01Z"
        )
        mutations.append(changed)

        for index, document in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(newsstore.NewsError):
                newsstore.validate_snapshot(
                    document, SOURCES, ENTITY_IDS, TOPIC_IDS, now=NOW
                )

    def test_stored_item_recomputes_identity_publisher_and_attribution(self):
        base = valid_snapshot([item_record()])
        for field, value in (
            ("id", "n_" + "0" * 64),
            ("publisher", "guessed.example"),
            ("attribution", "Unnamed publisher"),
            ("source_id", "unknown-source"),
        ):
            document = deepcopy(base)
            document["items"][0][field] = value
            with self.subTest(field=field), self.assertRaises(newsstore.NewsError):
                newsstore.validate_snapshot(
                    document, SOURCES, ENTITY_IDS, TOPIC_IDS, now=NOW
                )

    def test_stored_item_rejects_future_banned_and_invalid_taxonomy_data(self):
        base = valid_snapshot([item_record()])
        mutations = []
        for field, value in (
            ("published", "2026-08-21T12:05:01Z"),
            ("title", "Markets LIVE updates"),
            ("topic", "unknown-topic"),
            ("entities", ["unknown-entity"]),
        ):
            document = deepcopy(base)
            document["items"][0][field] = value
            if field == "published":
                document["items"] = sorted(
                    document["items"],
                    key=lambda row: (row["published"], row["id"]),
                    reverse=True,
                )
            mutations.append((field, document))
        for field, document in mutations:
            with self.subTest(field=field), self.assertRaises(newsstore.NewsError):
                newsstore.validate_snapshot(
                    document, SOURCES, ENTITY_IDS, TOPIC_IDS, now=NOW
                )

    def test_order_duplicates_envelope_and_item_fields_are_exact(self):
        older = item_record(
            url="https://www.federalreserve.gov/older",
            published="2026-08-19T00:00:00Z",
        )
        newer = item_record(
            url="https://www.federalreserve.gov/newer",
            published="2026-08-20T00:00:00Z",
        )
        base = valid_snapshot([older, newer])

        unordered = deepcopy(base)
        unordered["items"].reverse()
        duplicate = valid_snapshot([newer, newer])
        extra_envelope = dict(base, checked_at=NOW_ISO)
        extra_item = deepcopy(base)
        extra_item["items"][0]["summary"] = "not a public stored field"
        for document in (unordered, duplicate, extra_envelope, extra_item):
            with self.subTest(document=document), self.assertRaises(newsstore.NewsError):
                newsstore.validate_snapshot(
                    document, SOURCES, ENTITY_IDS, TOPIC_IDS, now=NOW
                )

    def test_serialized_snapshot_byte_ceiling_is_enforced(self):
        base = "https://www.federalreserve.gov/"
        records = []
        for index in range(newsstore.MAX_ITEMS):
            marker = f"{index:03d}"
            url = base + marker + "x" * (2_048 - len(base) - len(marker))
            records.append(item_record(
                url=url,
                title="H" * newsstore.MAX_TITLE_CHARS,
                published="2026-08-20T14:00:00Z",
            ))
        document = valid_snapshot(records)
        self.assertGreater(
            len(jsonio.dumps(document).encode("utf-8")),
            newsstore.MAX_SNAPSHOT_BYTES,
        )
        with self.assertRaises(newsstore.NewsError) as caught:
            newsstore.validate_snapshot(
                document, SOURCES, ENTITY_IDS, TOPIC_IDS, now=NOW
            )
        self.assertIn("bytes", str(caught.exception))


class TestRetention(unittest.TestCase):
    def test_incoming_replaces_same_identity_and_sort_is_deterministic(self):
        url = "https://www.federalreserve.gov/corrected"
        previous = [item_record(url=url, title="Old title")]
        incoming = NewsItem(
            id=newsstore.news_id(url),
            title="Corrected title",
            url=url,
            source_id=RSS_SOURCE.id,
            attribution=RSS_SOURCE.attribution,
            publisher="www.federalreserve.gov",
            published="2026-08-20T15:00:00Z",
            topic="rates-macro",
        )
        merged = newsstore.merge(
            previous, [incoming], {RSS_SOURCE.id: 365}, NOW
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["title"], "Corrected title")

    def test_retention_drops_stale_but_zero_retention_keeps_history(self):
        old = item_record(
            url="https://www.federalreserve.gov/old",
            published="2024-01-01T00:00:00Z",
        )
        new = item_record(
            url="https://www.federalreserve.gov/new",
            published="2026-08-20T00:00:00Z",
        )
        retained = newsstore.merge(
            [old, new], [], {RSS_SOURCE.id: 365}, NOW
        )
        self.assertEqual([row["url"] for row in retained], [new["url"]])
        self.assertEqual(
            len(newsstore.merge([old], [], {RSS_SOURCE.id: 0}, NOW)),
            1,
        )

    def test_retention_refuses_invalid_or_future_calendar_instants(self):
        for published in ("2026-02-30T00:00:00Z", "2026-08-21T12:05:01Z"):
            record = item_record(published=published)
            with self.subTest(published=published), self.assertRaises(newsstore.NewsError):
                newsstore.merge([record], [], {RSS_SOURCE.id: 365}, NOW)

    def test_item_count_is_capped_after_newest_first_sort(self):
        records = [
            item_record(
                url=f"https://www.federalreserve.gov/{index}",
                published="2026-08-20T00:00:00Z",
            )
            for index in range(newsstore.MAX_ITEMS + 20)
        ]
        merged = newsstore.merge(records, [], {}, NOW)
        self.assertEqual(len(merged), newsstore.MAX_ITEMS)
        expected = sorted(
            records,
            key=lambda record: (record["published"], record["id"]),
            reverse=True,
        )[:newsstore.MAX_ITEMS]
        self.assertEqual(merged, expected)


class TestLastKnownGoodPromotion(unittest.TestCase):
    def test_promote_then_load_round_trips_a_valid_schema_three_snapshot(self):
        document = valid_snapshot([item_record()])
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "news.json"
            newsstore.promote(
                document, SOURCES, ENTITY_IDS, TOPIC_IDS, target, now=NOW
            )
            loaded = newsstore.load(
                SOURCES, ENTITY_IDS, TOPIC_IDS, target, now=NOW
            )
        self.assertEqual(loaded, document)

    def test_invalid_promotion_leaves_exact_previous_bytes_untouched(self):
        document = valid_snapshot([item_record()])
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "news.json"
            newsstore.promote(
                document, SOURCES, ENTITY_IDS, TOPIC_IDS, target, now=NOW
            )
            before = target.read_bytes()
            invalid = deepcopy(document)
            invalid["schema_version"] = 999
            with self.assertRaises(newsstore.NewsError):
                newsstore.promote(
                    invalid, SOURCES, ENTITY_IDS, TOPIC_IDS, target, now=NOW
                )
            self.assertEqual(target.read_bytes(), before)

    def test_failed_atomic_writer_leaves_exact_previous_bytes_untouched(self):
        document = valid_snapshot([item_record()])
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "news.json"
            newsstore.promote(
                document, SOURCES, ENTITY_IDS, TOPIC_IDS, target, now=NOW
            )
            before = target.read_bytes()
            with mock.patch.object(
                jsonio, "write_atomic", side_effect=OSError("disk full")
            ):
                with self.assertRaises(OSError):
                    newsstore.promote(
                        document, SOURCES, ENTITY_IDS, TOPIC_IDS, target, now=NOW
                    )
            self.assertEqual(target.read_bytes(), before)

    def test_missing_store_returns_honest_never_checked_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            loaded = newsstore.load(
                SOURCES,
                ENTITY_IDS,
                TOPIC_IDS,
                Path(temporary) / "missing.json",
                now=NOW,
            )
        self.assertEqual(loaded, newsstore.empty_snapshot(SOURCES))

    def test_corrupt_or_duplicate_key_store_is_refused_not_replaced(self):
        payloads = (
            b"{not json",
            b'{"schema_version":3,"schema_version":3}',
        )
        for payload in payloads:
            with tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "news.json"
                target.write_bytes(payload)
                with self.subTest(payload=payload), self.assertRaises(newsstore.NewsError):
                    newsstore.load(
                        SOURCES, ENTITY_IDS, TOPIC_IDS, target, now=NOW
                    )
                self.assertEqual(target.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
