"""End-to-end build: determinism, containment, and validator agreement."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import build_site
import validate_data
from navnoor_research import manifest, render

ROOT = Path(__file__).resolve().parent


class TestRender(unittest.TestCase):
    ASSETS = {"css": "app-1.css", "js": "app-2.js", "articles": "articles-3.json",
              "news": "news-4.json", "taxonomy": "taxonomy-5.json"}

    def setUp(self):
        self.html = render.render(self.ASSETS, "abcdef1234567890", 559, 76)

    def test_declares_a_content_security_policy(self):
        self.assertIn("Content-Security-Policy", self.html)
        self.assertIn("default-src 'none'", self.html)

    def test_frame_ancestors_is_not_used_in_meta(self):
        # It is ignored there, and the browser logs a console error for it.
        self.assertNotIn("frame-ancestors", self.html)

    def test_references_no_off_origin_asset(self):
        self.assertIsNone(re.search(r'(?:src|href)="(?:https?:)?//', self.html))

    def test_carries_every_payload_name(self):
        for name in self.ASSETS.values():
            self.assertIn(name, self.html)

    def test_reports_the_revision(self):
        self.assertIn("abcdef123456", self.html)

    def test_escapes_asset_names(self):
        html = render.render(dict(self.ASSETS, css='a"><script>x</script>'), "r", 0, 0)
        self.assertNotIn("<script>x</script>", html)


class TestBuild(unittest.TestCase):
    def build(self, out: Path, revision: str = "testrev") -> dict:
        code = build_site.main(["--out", str(out), "--revision", revision])
        self.assertEqual(code, 0)
        return json.loads((out / manifest.MANIFEST_NAME).read_text(encoding="utf-8"))

    def test_build_is_byte_identical_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a"
            second = Path(tmp) / "b"
            release_a = self.build(first)
            release_b = self.build(second)
            self.assertEqual(release_a["files"], release_b["files"])

    def test_manifest_verifies_against_its_own_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            release = self.build(out, "rev-under-test")
            self.assertEqual(manifest.verify(out, release, "rev-under-test"), [])

    def test_rebuild_removes_stale_fingerprinted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            (out / "stale-0000.js").write_text("old", encoding="utf-8")
            release = self.build(out)
            self.assertNotIn("stale-0000.js", [f["path"] for f in release["files"]])
            self.assertFalse((out / "stale-0000.js").exists())

    def test_bundle_contains_no_member_or_body_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            for path in out.rglob("*.json"):
                text = path.read_text(encoding="utf-8")
                for banned in ("member_preview", "body_text", "parser_observations"):
                    self.assertNotIn(banned, text, f"{path.name} leaks {banned}")

    def test_nojekyll_is_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            self.assertTrue((out / ".nojekyll").exists())


class TestValidatorsAgree(unittest.TestCase):
    def test_shipped_data_validates(self):
        self.assertEqual(validate_data.main([]), 0)

    def test_release_validator_accepts_a_fresh_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            build_site.main(["--out", str(out), "--revision", "rev-x"])
            result = subprocess.run(
                [sys.executable, "validate_release.py", "--site", str(out),
                 "--expected-revision", "rev-x"],
                cwd=str(ROOT), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_smoke_test_passes_on_a_fresh_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            build_site.main(["--out", str(out), "--revision", "rev-y"])
            result = subprocess.run(
                [sys.executable, "smoke_test_site.py", "--site", str(out)],
                cwd=str(ROOT), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


class TestDataValidatorCatchesProblems(unittest.TestCase):
    def test_unknown_topic_is_rejected(self):
        doc = {"schema_version": 2, "articles": [{
            "id": "a", "title": "t", "url": "https://x/", "source": "substack",
            "published": "2026-01-01", "access": "free", "topic": "nope", "entities": []}]}
        errors = validate_data.validate_articles(doc, set(), {"general"})
        self.assertTrue(any("unknown topic" in e for e in errors))

    def test_forbidden_field_is_rejected(self):
        doc = {"schema_version": 2, "articles": [{
            "id": "a", "title": "t", "url": "https://x/", "source": "substack",
            "published": "2026-01-01", "access": "free", "topic": "general",
            "entities": [], "body_text": "leak"}]}
        errors = validate_data.validate_articles(doc, set(), {"general"})
        self.assertTrue(any("forbidden" in e for e in errors))

    def test_http_url_is_rejected(self):
        doc = {"schema_version": 2, "articles": [{
            "id": "a", "title": "t", "url": "http://x/", "source": "substack",
            "published": "2026-01-01", "access": "free", "topic": "general", "entities": []}]}
        errors = validate_data.validate_articles(doc, set(), {"general"})
        self.assertTrue(any("https" in e for e in errors))

    def test_duplicate_id_is_rejected(self):
        record = {"id": "a", "title": "t", "url": "https://x/", "source": "substack",
                  "published": "2026-01-01", "access": "free", "topic": "general", "entities": []}
        doc = {"schema_version": 2, "articles": [record, dict(record)]}
        errors = validate_data.validate_articles(doc, set(), {"general"})
        self.assertTrue(any("duplicate id" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
