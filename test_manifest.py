"""Release manifests fail closed on files, aggregates, shape, order, and paths."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path

from navnoor_research import manifest


class TestManifest(unittest.TestCase):
    def bundle(self, root: str) -> Path:
        site = Path(root) / "site"
        site.mkdir()
        (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (site / "app-abc.css").write_text("body{}", encoding="utf-8")
        return site

    def release(self, site: Path) -> dict:
        return manifest.build(site, "a" * 40, {"research": 2})

    def test_clean_bundle_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self.bundle(tmp)
            release = self.release(site)
            self.assertEqual(manifest.verify(site, release, "a" * 40), [])

    def test_file_edit_missing_and_unlisted_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self.bundle(tmp)
            release = self.release(site)
            (site / "app-abc.css").write_text("changed", encoding="utf-8")
            self.assertTrue(any("app-abc.css" in problem
                                for problem in manifest.verify(site, release)))
            (site / "app-abc.css").unlink()
            self.assertTrue(any("missing from bundle" in problem
                                for problem in manifest.verify(site, release)))
            (site / "extra.js").write_text("x", encoding="utf-8")
            self.assertTrue(any("unlisted" in problem
                                for problem in manifest.verify(site, release)))

    def test_declared_aggregates_are_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self.bundle(tmp)
            for field, value in (("file_count", 999), ("total_bytes", 999999)):
                release = self.release(site)
                release[field] = value
                self.assertTrue(manifest.verify(site, release), field)
            release = self.release(site)
            release["counts"] = {"research": -1}
            self.assertTrue(any("counts" in problem for problem in manifest.verify(site, release)))

    def test_duplicate_and_unsafe_paths_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self.bundle(tmp)
            release = self.release(site)
            release["files"].append(copy.deepcopy(release["files"][0]))
            release["file_count"] += 1
            release["total_bytes"] += release["files"][-1]["bytes"]
            self.assertTrue(any("duplicate" in problem
                                for problem in manifest.verify(site, release)))
            for unsafe in (
                "../escape", "/absolute", "bad\\path", "has space", "./index.html",
                "nested/index.html", "https://evil.example/file",
            ):
                mutated = self.release(site)
                mutated["files"][0]["path"] = unsafe
                self.assertTrue(manifest.verify(site, mutated), unsafe)

    def test_order_shape_revision_and_digest_syntax_are_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self.bundle(tmp)
            release = self.release(site)
            release["files"].reverse()
            self.assertTrue(any("order" in problem for problem in manifest.verify(site, release)))
            release = self.release(site)
            release["extra"] = True
            problems = manifest.verify(site, release)
            self.assertTrue(any("envelope" in problem for problem in problems))
            release = self.release(site)
            release["files"][0]["sha256"] = "nope"
            self.assertTrue(any("digest" in problem for problem in manifest.verify(site, release)))
            self.assertTrue(any("revision mismatch" in problem
                                for problem in manifest.verify(site, self.release(site), "b" * 40)))

    @unittest.skipIf(not hasattr(os, "symlink"), "symlinks unavailable")
    def test_symbolic_link_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self.bundle(tmp)
            os.symlink(site / "index.html", site / "linked.html")
            release = self.release(site)
            self.assertTrue(any("symbolic link" in problem
                                for problem in manifest.verify(site, release)))

    def test_manifest_never_lists_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self.bundle(tmp)
            (site / manifest.MANIFEST_NAME).write_text("{}", encoding="utf-8")
            release = self.release(site)
            self.assertNotIn(manifest.MANIFEST_NAME, [entry["path"] for entry in release["files"]])

    def test_non_object_manifest_is_refused_without_attribute_access(self):
        self.assertTrue(manifest.validate_document([], "a" * 40))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(manifest.verify(Path(tmp), [], "a" * 40))


if __name__ == "__main__":
    unittest.main()
