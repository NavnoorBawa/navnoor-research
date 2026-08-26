"""Boundary and aggregation tests for the independent freshness policy."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from navnoor_research import freshness

NOW = datetime(2026, 8, 26, 6, 0, 0, tzinfo=timezone.utc)


def stamp(delta: timedelta) -> str:
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def documents():
    seed = {"source_snapshot": {"checked_at": stamp(timedelta(hours=1))}}
    companies = {"checked_at": stamp(timedelta(hours=1))}
    news = {
        "sources": {
            "federal-reserve-rss": {
                "last_attempt_at": stamp(timedelta(hours=1)),
                "last_success_at": stamp(timedelta(hours=1)),
                "status": "ok",
            }
        }
    }
    return seed, companies, news


class TestFreshnessPolicy(unittest.TestCase):
    def evaluate(self, seed=None, companies=None, news=None):
        defaults = documents()
        return freshness.evaluate(
            seed if seed is not None else defaults[0],
            companies if companies is not None else defaults[1],
            news if news is not None else defaults[2],
            now=NOW,
        )

    def test_exact_age_and_future_skew_boundaries_pass(self):
        seed, companies, news = documents()
        seed["source_snapshot"]["checked_at"] = stamp(timedelta(hours=36))
        companies["checked_at"] = stamp(timedelta(hours=72))
        state = news["sources"]["federal-reserve-rss"]
        state["last_attempt_at"] = stamp(timedelta(hours=12))
        state["last_success_at"] = stamp(timedelta(hours=48))

        errors, warnings = self.evaluate(seed, companies, news)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

        future = (NOW + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        seed["source_snapshot"]["checked_at"] = future
        errors, _ = self.evaluate(seed, companies, news)
        self.assertEqual(errors, [])

    def test_every_stale_control_plane_is_reported_together(self):
        seed, companies, news = documents()
        seed["source_snapshot"]["checked_at"] = stamp(
            timedelta(hours=36, seconds=1)
        )
        companies["checked_at"] = stamp(timedelta(hours=72, seconds=1))
        news["sources"] = {
            "federal-reserve-rss": {
                "last_attempt_at": stamp(timedelta(hours=12, seconds=1)),
                "last_success_at": stamp(timedelta(hours=48, seconds=1)),
                "status": "ok",
            },
            "gdelt-doc": {
                "last_attempt_at": stamp(timedelta(hours=12, seconds=1)),
                "last_success_at": stamp(timedelta(days=7)),
                "status": "error",
            },
        }

        errors, warnings = self.evaluate(seed, companies, news)

        self.assertEqual(len(errors), 4)
        self.assertTrue(any("archive" in message for message in errors))
        self.assertTrue(any("SEC company" in message for message in errors))
        self.assertTrue(any(
            "federal-reserve-rss has not been attempted" in message
            for message in errors
        ))
        self.assertTrue(any("gdelt-doc has not been attempted" in message for message in errors))
        self.assertEqual(len(warnings), 1)
        self.assertIn("gdelt-doc is 'error'", warnings[0])

    def test_recent_degraded_attempt_warns_without_rejecting_last_known_good(self):
        seed, companies, news = documents()
        news["sources"]["gdelt-doc"] = {
            "last_attempt_at": stamp(timedelta(minutes=5)),
            "last_success_at": stamp(timedelta(days=7)),
            "status": "error",
        }

        errors, warnings = self.evaluate(seed, companies, news)

        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("has not succeeded in 48 hours", warnings[0])
        self.assertIn("validated last-known-good", warnings[0])

    def test_future_and_impossible_success_relationships_are_aggregated(self):
        seed, companies, news = documents()
        seed["source_snapshot"]["checked_at"] = (
            NOW + timedelta(minutes=10, seconds=1)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = news["sources"]["federal-reserve-rss"]
        state["last_attempt_at"] = stamp(timedelta(minutes=2))
        state["last_success_at"] = stamp(timedelta(minutes=1))

        errors, _ = self.evaluate(seed, companies, news)

        self.assertEqual(len(errors), 2)
        self.assertTrue(any("implausibly in the future" in message for message in errors))
        self.assertTrue(any("later than its last attempt" in message for message in errors))

    def test_malformed_fields_and_all_sources_are_not_fail_fast(self):
        seed, companies, news = documents()
        seed["source_snapshot"]["checked_at"] = "not-a-time"
        companies.pop("checked_at")
        news["sources"] = {
            "federal-reserve-rss": {
                "last_attempt_at": "bad",
                "last_success_at": "also-bad",
                "status": "ok",
            },
            "gdelt-doc": {
                "last_attempt_at": "bad-again",
                "last_success_at": None,
                "status": "never",
            },
        }

        errors, warnings = self.evaluate(seed, companies, news)

        self.assertEqual(len(errors), 5)
        self.assertEqual(len(warnings), 2)

    def test_clock_must_be_timezone_aware(self):
        seed, companies, news = documents()
        with self.assertRaises(freshness.FreshnessError):
            freshness.evaluate(
                seed, companies, news, now=datetime(2026, 8, 26, 6, 0, 0)
            )


if __name__ == "__main__":
    unittest.main()
