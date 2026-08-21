"""The release manifest must detect any drift between itself and the bundle."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from navnoor_research import manifest


class TestManifest(unittest.TestCase):
    def _bundle(self, tmp: str) -> Path:
        site = Path(tmp) / "site"
        site.mkdir()
        (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (site / "app-abc.css").write_text("body{}", encoding="utf-8")
        return site

    def test_clean_bundle_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._bundle(tmp)
            release = manifest.build(site, "rev1", {"articles": 2})
            self.assertEqual(manifest.verify(site, release, "rev1"), [])
            self.assertEqual(release["file_count"], 2)

    def test_edited_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._bundle(tmp)
            release = manifest.build(site, "rev1", {})
            (site / "app-abc.css").write_text("body{color:red}", encoding="utf-8")
            problems = manifest.verify(site, release)
            self.assertTrue(any("app-abc.css" in p for p in problems))

    def test_missing_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._bundle(tmp)
            release = manifest.build(site, "rev1", {})
            (site / "app-abc.css").unlink()
            self.assertTrue(any("missing from bundle" in p for p in manifest.verify(site, release)))

    def test_unlisted_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._bundle(tmp)
            release = manifest.build(site, "rev1", {})
            (site / "sneaked.js").write_text("alert(1)", encoding="utf-8")
            self.assertTrue(any("unlisted" in p for p in manifest.verify(site, release)))

    def test_revision_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._bundle(tmp)
            release = manifest.build(site, "rev1", {})
            self.assertTrue(any("revision mismatch" in p
                                for p in manifest.verify(site, release, "rev2")))

    def test_manifest_does_not_list_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._bundle(tmp)
            (site / manifest.MANIFEST_NAME).write_text("{}", encoding="utf-8")
            release = manifest.build(site, "rev1", {})
            self.assertNotIn(manifest.MANIFEST_NAME, [f["path"] for f in release["files"]])


if __name__ == "__main__":
    unittest.main()
