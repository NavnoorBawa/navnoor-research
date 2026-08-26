"""Exact-revision, metadata-only research seed security contract."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import unittest
from copy import deepcopy
from unittest import mock

from navnoor_research import jsonio, seed

REVISION = "a" * 40


def article(**overrides):
    record = {
        "source": "substack",
        "source_id": "alpha",
        "slug": "alpha",
        "title": "Alpha research",
        "subtitle": "Public metadata only.",
        "post_date": "2026-08-20T13:31:31.862Z",
        "url": "https://navnoorbawa.substack.com/p/alpha",
        "alternate_urls": {},
        "audience": "everyone",
        # These values are deliberately outside the reviewed projection.
        "member_preview": "MEMBER_SENTINEL_MUST_NOT_SURVIVE",
        "body_text": "BODY_SENTINEL_MUST_NOT_SURVIVE",
        "brief": {"lead": {"text": "BODY_LEAD_MUST_NOT_SURVIVE"}},
        "wordcount": 999_999,
    }
    record.update(overrides)
    return record


def source_files(record=None, trades=None):
    selected = article() if record is None else record
    observations = [{"position": "OMITTED_TRADE_SENTINEL"}] if trades is None else trades
    article_payload = jsonio.dumps([selected]).encode("utf-8")
    trade_payload = jsonio.dumps(observations).encode("utf-8")
    checksum = hashlib.sha256(article_payload + b"\0" + trade_payload).hexdigest()
    checked = "2026-08-22T12:00:00Z"
    snapshot = {
        "article_count": 1,
        "catalog_count": 1,
        "catalog_latest_publication": "2026-08-20T13:31:31.862Z",
        "checked_at": checked,
        "data_checksum": checksum,
        "observation_count": len(observations),
        "registry_count": 0,
        "schema_version": 2,
        "sources": {
            "substack": {
                "checked_at": checked,
                "included_count": 1,
                "newest": "2026-08-20T13:31:31.862Z",
                "status": "ok",
            }
        },
    }
    return {
        "articles_index.json": article_payload,
        "trades_extracted.json": trade_payload,
        "snapshot_manifest.json": jsonio.dumps(snapshot).encode("utf-8"),
    }


def cross_post_source_files():
    """Model a newest Medium discovery retained canonically as Substack."""
    records = [
        article(
            alternate_urls={"medium": "https://medium.com/@navnoorbawa/alpha"},
        ),
        article(
            source="medium",
            source_id="older-medium",
            slug="older-medium",
            title="Older Medium research",
            post_date="2026-08-19T10:00:00Z",
            url="https://medium.com/@navnoorbawa/older-medium",
            audience="public",
        ),
    ]
    files = source_files()
    article_payload = jsonio.dumps(records).encode("utf-8")
    trade_payload = files["trades_extracted.json"]
    snapshot = jsonio.loads_strict(files["snapshot_manifest.json"])
    snapshot.update({
        "article_count": 2,
        "catalog_count": 2,
        "data_checksum": hashlib.sha256(
            article_payload + b"\0" + trade_payload
        ).hexdigest(),
    })
    snapshot["sources"]["medium"] = {
        "checked_at": snapshot["checked_at"],
        "included_count": 1,
        # This is the discovered cross-post above, not the older canonical
        # Medium record that remains after source merging.
        "newest": records[0]["post_date"],
        "status": "ok",
    }
    files["articles_index.json"] = article_payload
    files["snapshot_manifest.json"] = jsonio.dumps(snapshot).encode("utf-8")
    return files


def git_archive(files, *, comment=REVISION, mode="w:"):
    payload = io.BytesIO()
    kwargs = {
        "fileobj": payload,
        "mode": mode,
        "format": tarfile.PAX_FORMAT,
    }
    if comment is not None:
        kwargs["pax_headers"] = {"comment": comment}
    with tarfile.open(**kwargs) as archive:
        for name, body in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(body)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(body))
    return payload.getvalue()


class TestSelectiveJsonReader(unittest.TestCase):
    def test_only_reviewed_top_level_fields_are_materialised(self):
        class GuardedDecoder(json.JSONDecoder):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def raw_decode(self, text, idx=0):
                self.calls += 1
                if text.startswith('"NEVER_MATERIALISE_ME"', idx):
                    raise AssertionError("an unreviewed value reached JSON materialisation")
                return super().raw_decode(text, idx)

        raw = article(member_preview="NEVER_MATERIALISE_ME")
        payload = jsonio.dumps([raw]).encode("utf-8")
        decoder = GuardedDecoder()
        with mock.patch.object(seed, "_strict_decoder", return_value=decoder):
            selected = seed.select_article_fields(payload)
        self.assertGreater(decoder.calls, 0, "the selective decoder must be operative")
        self.assertEqual(set(selected[0]), seed.SELECTED_ARTICLE_KEYS & set(raw))
        encoded = jsonio.dumps(selected)
        self.assertNotIn("NEVER_MATERIALISE_ME", encoded)
        self.assertNotIn("member_preview", encoded)

    def test_unreviewed_nested_values_are_validated_without_surviving(self):
        raw = article(
            member_preview={"nested": [1, {"sentinel": "DO_NOT_PUBLISH"}]},
            body_text=1e300,
        )
        selected = seed.select_article_fields(jsonio.dumps([raw]).encode("utf-8"))
        self.assertEqual(len(selected), 1)
        self.assertNotIn("DO_NOT_PUBLISH", jsonio.dumps(selected))

    def test_duplicate_keys_are_refused_even_inside_skipped_values(self):
        payloads = (
            b'[{"title":"one","title":"two"}]',
            b'[{"title":"one","body":{"lead":1,"lead":2}}]',
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(seed.SeedError):
                seed.select_article_fields(payload)

    def test_invalid_utf8_nonfinite_and_trailing_json_are_refused(self):
        payloads = (
            b"\xff",
            b'[{"title":"one","body":NaN}]',
            b'[{"title":"one"}] trailing',
            b'{"title":"not an array"}',
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(seed.SeedError):
                seed.select_article_fields(payload)

    def test_observation_array_is_counted_without_returning_values(self):
        payload = b'[{"position":"SECRET"},[1,2,3],null]'
        self.assertEqual(seed.count_array_items(payload, "trades_extracted.json"), 3)
        with self.assertRaises(seed.SeedError):
            seed.count_array_items(b'[{"x":1,"x":2}]', "trades_extracted.json")


class TestExactGitArchive(unittest.TestCase):
    def test_exact_three_members_and_matching_pax_revision_are_accepted(self):
        files = source_files()
        read = seed.read_git_archive(git_archive(files), REVISION)
        self.assertEqual(read, files)

    def test_missing_pax_revision_is_refused(self):
        with self.assertRaises(seed.SeedError) as caught:
            seed.read_git_archive(git_archive(source_files(), comment=None), REVISION)
        self.assertIn("comment", str(caught.exception))

    def test_wrong_pax_revision_is_refused(self):
        with self.assertRaises(seed.SeedError) as caught:
            seed.read_git_archive(git_archive(source_files(), comment="b" * 40), REVISION)
        self.assertIn("does not match", str(caught.exception))

    def test_compressed_tar_is_refused(self):
        compressed = git_archive(source_files(), mode="w:gz")
        with self.assertRaises(seed.SeedError):
            seed.read_git_archive(compressed, REVISION)

    def test_member_set_must_be_closed_and_regular(self):
        missing = source_files()
        del missing["trades_extracted.json"]
        with self.assertRaises(seed.SeedError):
            seed.read_git_archive(git_archive(missing), REVISION)

        extra = source_files()
        extra["unexpected.json"] = b"{}"
        with self.assertRaises(seed.SeedError):
            seed.read_git_archive(git_archive(extra), REVISION)

    def test_revision_must_be_full_lowercase_commit(self):
        archive = git_archive(source_files())
        for revision in ("a" * 39, "A" * 40, "main", ""):
            with self.subTest(revision=revision), self.assertRaises(seed.SeedError):
                seed.read_git_archive(archive, revision)


class TestProjectionAndCommitMarker(unittest.TestCase):
    def project(self, record=None):
        return seed.project(source_files(record), REVISION)

    def test_projection_is_exact_metadata_only(self):
        publications, provenance = self.project()
        self.assertEqual(set(publications), {
            "dataset", "records", "rights_profile", "schema_version",
            "source_dataset_version",
        })
        self.assertEqual(len(publications["records"]), 1)
        record = publications["records"][0]
        self.assertEqual(set(record), seed.RECORD_KEYS)
        self.assertEqual(record["access"], "public")
        self.assertEqual(record["id"], seed.publication_id("substack", "alpha"))
        encoded = jsonio.dumps(publications)
        for sentinel in (
            "MEMBER_SENTINEL", "BODY_SENTINEL", "BODY_LEAD", "OMITTED_TRADE",
            "wordcount", "brief", "member_preview",
        ):
            self.assertNotIn(sentinel, encoded)
        roles = {entry["path"]: entry["role"] for entry in provenance["inputs"]}
        self.assertEqual(roles["articles_index.json"], "projected")
        self.assertEqual(roles["trades_extracted.json"], "checksum-companion-only")

    def test_generated_pair_validates_as_one_transaction(self):
        publications, provenance = self.project()
        publication_bytes = jsonio.dumps_pretty(publications).encode("utf-8")
        manifest_bytes = jsonio.dumps_pretty(provenance).encode("utf-8")
        checked, marker = seed.validate_stored(publication_bytes, manifest_bytes)
        self.assertEqual(checked, publications)
        self.assertEqual(marker, provenance)

    def test_manifest_binds_exact_publication_bytes(self):
        publications, provenance = self.project()
        publication_bytes = jsonio.dumps_pretty(publications).encode("utf-8")
        manifest_bytes = jsonio.dumps_pretty(provenance).encode("utf-8")
        with self.assertRaises(seed.SeedError):
            seed.validate_stored(publication_bytes + b" ", manifest_bytes)

        changed = deepcopy(publications)
        changed["records"][0]["title"] = "Changed after marker creation"
        with self.assertRaises(seed.SeedError):
            seed.validate_stored(
                jsonio.dumps_pretty(changed).encode("utf-8"), manifest_bytes
            )

    def test_duplicate_and_nonfinite_stored_json_are_refused(self):
        publications, provenance = self.project()
        manifest_bytes = jsonio.dumps_pretty(provenance).encode("utf-8")
        bad_publications = (
            b'{"dataset":"x","dataset":"y"}',
            b'{"dataset":"x","n":NaN}',
            b"\xff",
        )
        for payload in bad_publications:
            with self.subTest(payload=payload), self.assertRaises(seed.SeedError):
                seed.validate_stored(payload, manifest_bytes)

        publication_bytes = jsonio.dumps_pretty(publications).encode("utf-8")
        with self.assertRaises(seed.SeedError):
            seed.validate_stored(
                publication_bytes,
                b'{"schema_version":1,"schema_version":1}',
            )

    def test_calendar_dates_are_real_not_merely_well_shaped(self):
        for value in (
            "2026-02-30",
            "2026-13-01",
            "2026-08-20T25:00:00Z",
            "2026-08-20T12:60:00Z",
            "2026-08-20T12:00:00+00:00",
        ):
            with self.subTest(value=value), self.assertRaises(seed.SeedError):
                self.project(article(post_date=value))

    def test_canonical_urls_are_https_host_bound_and_path_bound(self):
        invalid = (
            "http://navnoorbawa.substack.com/p/alpha",
            "https://evil.example/p/alpha",
            "https://navnoorbawa.substack.com:444/p/alpha",
            "https://user@navnoorbawa.substack.com/p/alpha",
            "https://navnoorbawa.substack.com/p/alpha#fragment",
            "https://navnoorbawa.substack.com/p/not-alpha",
            "https://navnoorbawa.substack.com/p/alpha\n",
            "https://navnoorbawa.substack.com:bogus/p/alpha",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(seed.SeedError):
                self.project(article(url=url))

    def test_alternate_url_label_and_host_are_both_reviewed(self):
        invalid = (
            {"unknown": "https://medium.com/@navnoorbawa/alpha"},
            {"medium": "https://evil.example/alpha"},
            {"medium": "https://medium.com/@navnoorbawa/alpha#fragment"},
        )
        for alternate in invalid:
            with self.subTest(alternate=alternate), self.assertRaises(seed.SeedError):
                self.project(article(alternate_urls=alternate))

    def test_snapshot_json_is_strict_and_binds_exact_inputs(self):
        files = source_files()
        files["snapshot_manifest.json"] = (
            b'{"schema_version":2,"schema_version":2}'
        )
        with self.assertRaises(seed.SeedError):
            seed.project(files, REVISION)

    def test_source_aggregate_counts_and_latest_dates_are_recomputed(self):
        for field, value in (
            ("article_count", 2),
            ("registry_count", 1),
            ("catalog_latest_publication", "2026-08-19T13:31:31Z"),
        ):
            files = source_files()
            snapshot = jsonio.loads_strict(files["snapshot_manifest.json"])
            snapshot[field] = value
            files["snapshot_manifest.json"] = jsonio.dumps(snapshot).encode("utf-8")
            with self.subTest(field=field), self.assertRaises(seed.SeedError):
                seed.project(files, REVISION)

        files = source_files()
        snapshot = jsonio.loads_strict(files["snapshot_manifest.json"])
        snapshot["sources"]["substack"]["included_count"] = 2
        files["snapshot_manifest.json"] = jsonio.dumps(snapshot).encode("utf-8")
        with self.assertRaises(seed.SeedError):
            seed.project(files, REVISION)

        files = source_files()
        snapshot = jsonio.loads_strict(files["snapshot_manifest.json"])
        snapshot["data_checksum"] = "0" * 64
        files["snapshot_manifest.json"] = jsonio.dumps(snapshot).encode("utf-8")
        with self.assertRaises(seed.SeedError):
            seed.project(files, REVISION)

    def test_source_newest_preserves_the_pre_deduplication_discovery_edge(self):
        publications, provenance = seed.project(cross_post_source_files(), REVISION)

        self.assertEqual(len(publications["records"]), 2)
        self.assertEqual(provenance["counts"]["by_source"], {
            "medium": 1,
            "substack": 1,
        })
        self.assertEqual(
            provenance["source_checks"]["medium"]["newest"],
            "2026-08-20T13:31:31.862Z",
        )

    def test_source_newest_cannot_predate_retained_canonical_records(self):
        files = cross_post_source_files()
        snapshot = jsonio.loads_strict(files["snapshot_manifest.json"])
        snapshot["sources"]["medium"]["newest"] = "2026-08-18T10:00:00Z"
        files["snapshot_manifest.json"] = jsonio.dumps(snapshot).encode("utf-8")

        with self.assertRaisesRegex(seed.SeedError, "predates its retained records"):
            seed.project(files, REVISION)

    def test_publishable_degraded_archive_source_is_preserved(self):
        files = source_files()
        snapshot = jsonio.loads_strict(files["snapshot_manifest.json"])
        snapshot["sources"]["substack"]["status"] = "degraded"
        files["snapshot_manifest.json"] = jsonio.dumps(snapshot).encode("utf-8")

        _, provenance = seed.project(files, REVISION)

        self.assertEqual(provenance["source_checks"]["substack"]["status"], "degraded")

    def test_unpublishable_archive_source_status_is_rejected(self):
        files = source_files()
        snapshot = jsonio.loads_strict(files["snapshot_manifest.json"])
        snapshot["sources"]["substack"]["status"] = "failed"
        files["snapshot_manifest.json"] = jsonio.dumps(snapshot).encode("utf-8")

        with self.assertRaisesRegex(seed.SeedError, "is not publishable"):
            seed.project(files, REVISION)


if __name__ == "__main__":
    unittest.main()
