"""Refresh failures retain checked items while publishing honest source states."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import refresh_news
from navnoor_research import jsonio, newsstore, paths
from navnoor_research.adapters import gdelt, rss


class TestRefreshNewsFailures(unittest.TestCase):
    def test_all_source_failure_records_attempts_and_retains_items(self):
        previous = jsonio.load(paths.NEWS_PATH)
        # A refresh attempt happens now, never at a fixed instant that the stored
        # snapshot can overtake once the scheduled refresh records a newer success.
        attempted_at = newsstore.utc_now_iso()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "news.json"
            target.write_text(jsonio.dumps_pretty(previous), encoding="utf-8")
            with (
                mock.patch.object(paths, "NEWS_PATH", target),
                mock.patch.object(newsstore, "utc_now_iso", return_value=attempted_at),
                mock.patch.object(rss, "collect", side_effect=rss.FeedError("offline")),
                mock.patch.object(gdelt, "collect", side_effect=gdelt.GdeltError("offline")),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = refresh_news.main([])

            current = jsonio.load(target)

        self.assertEqual(result, 1)
        self.assertEqual(current["items"], previous["items"])
        self.assertEqual(set(current["sources"]), {
            "federal-reserve-rss", "gdelt-doc-v2",
        })
        for source_id, state in current["sources"].items():
            self.assertEqual(state["status"], "error", source_id)
            self.assertEqual(state["last_attempt_at"], attempted_at, source_id)
            self.assertEqual(
                state["last_success_at"],
                previous["sources"][source_id]["last_success_at"],
                source_id,
            )


if __name__ == "__main__":
    unittest.main()
