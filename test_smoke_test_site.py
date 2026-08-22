"""The deployed smoke test validates manifest paths before making asset requests."""

from __future__ import annotations

import unittest
from unittest import mock

import smoke_test_site
from navnoor_research import jsonio
from navnoor_research.schema import RELEASE_SCHEMA_VERSION

REVISION = "a" * 40


class TestRemoteManifestBoundary(unittest.TestCase):
    def malicious_release(self, path: str) -> bytes:
        document = {
            "counts": {"research": 1},
            "file_count": 1,
            "files": [{"bytes": 1, "path": path, "sha256": "b" * 64}],
            "revision": REVISION,
            "schema_version": RELEASE_SCHEMA_VERSION,
            "total_bytes": 1,
        }
        return jsonio.dumps(document).encode("utf-8")

    def test_absolute_or_nested_manifest_path_is_never_requested(self):
        for path in ("https://evil.example/payload", "../escape", "nested/file.js"):
            with self.subTest(path=path), mock.patch.object(
                smoke_test_site,
                "_get",
                return_value=(self.malicious_release(path), "application/json"),
            ) as get:
                _, failures = smoke_test_site.check("https://good.example/", REVISION)
                self.assertTrue(any("unsafe" in failure for failure in failures))
                get.assert_called_once_with(
                    "https://good.example/",
                    "release.json",
                    smoke_test_site.MAX_RELEASE_BYTES,
                )

    def test_non_object_release_is_refused_before_file_iteration(self):
        with mock.patch.object(
            smoke_test_site,
            "_get",
            return_value=(b"[]", "application/json"),
        ) as get:
            release, failures = smoke_test_site.check("https://good.example/", REVISION)
        self.assertEqual(release, {})
        self.assertTrue(any("envelope" in failure for failure in failures))
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
