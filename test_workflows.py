"""Operational workflow contracts for independent refresh and monitor domains."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


class TestWorkflowFailureDomains(unittest.TestCase):
    def assert_ordered(self, text: str, *needles: str) -> None:
        position = -1
        for needle in needles:
            found = text.find(needle, position + 1)
            self.assertGreater(found, position, f"{needle!r} is missing or out of order")
            position = found

    def test_scheduled_refresh_has_a_validated_three_file_seed_fallback(self):
        text = workflow("refresh.yml")

        self.assertNotIn("requirements-dev.txt", text)
        self.assertNotIn("needs: static_analysis", text)
        self.assertIn("refresh_seed_candidate() (", text)
        self.assertIn("for attempt in 1 2 3; do", text)
        self.assertIn("git restore", text)
        self.assertIn('--source="$BASELINE_REVISION"', text)
        for path in (
            "seed/publications.json",
            "seed/manifest.json",
            "data/research.json",
        ):
            self.assertGreaterEqual(text.count(path), 2)
        self.assert_ordered(
            text,
            "if refresh_seed_candidate; then",
            "git restore",
            "python3 validate_data.py",
            "git diff --exit-code",
            "Research seed refresh degraded",
            "Refresh SEC company associations",
            "Refresh reviewed checked-headline sources",
            "Validate changed data before it is eligible to commit",
        )

    def test_watchdog_runs_exact_bytes_and_freshness_independently(self):
        text = workflow("watchdog.yml")

        self.assert_ordered(
            text,
            "Rebuild and verify exact production bytes",
            './watchdog.sh "$GITHUB_SHA" --exact-only',
            "Verify scheduled data freshness",
            "python3 check_freshness.py",
            "EXACT_OUTCOME:",
            "FRESHNESS_OUTCOME:",
            "Exact published release failed",
            "Published data freshness failed",
        )

    def test_deployment_certifies_exact_bytes_and_freshness_separately(self):
        text = workflow("deploy.yml")

        self.assert_ordered(
            text,
            "Verify exact revision and bytes are live",
            './watchdog.sh "$GITHUB_SHA" --exact-only',
            "Verify published data freshness",
            "python3 check_freshness.py",
            "SMOKE_OUTCOME:",
            "FRESHNESS_OUTCOME:",
            "Exact production certification failed",
            "Published data freshness failed",
        )

    def test_default_watchdog_proves_live_bytes_before_freshness(self):
        text = (ROOT / "watchdog.sh").read_text(encoding="utf-8")

        self.assertIn("export SSL_CERT_FILE=/etc/ssl/cert.pem", text)
        self.assert_ordered(
            text,
            "python3 smoke_test_site.py \\",
            'echo "Production release is exact',
            "python3 check_freshness.py",
        )


if __name__ == "__main__":
    unittest.main()
