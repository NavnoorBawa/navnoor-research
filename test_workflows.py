"""Operational workflow contracts for independent refresh and monitor domains."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent


def workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def run_block(name: str, step_name: str) -> str:
    step = workflow(name).split(f"      - name: {step_name}", 1)[1]
    body = step.split("        run: |\n", 1)[1]
    return textwrap.dedent(body.split("\n      - name:", 1)[0].split("\n  static_analysis:", 1)[0])


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
            'if [ "$seed_status" -eq 0 ]; then',
            "git restore",
            "python3 validate_data.py",
            "git diff --exit-code",
            "Research seed refresh degraded",
            "Refresh SEC company associations",
            "Refresh reviewed checked-headline sources",
            "Validate changed data before it is eligible to commit",
        )

    def test_seed_refresh_failures_restore_baseline_without_running_later_stages(self):
        text = workflow("refresh.yml")
        step = text.split("      - name: Refresh exact research seed", 1)[1]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1].split(
            "\n      - name:", 1
        )[0])
        fake_command = '''
import os
import sys
from pathlib import Path

args = sys.argv[1:]
name = Path(sys.argv[0]).name
failure = os.environ["FAIL_STAGE"]
paths = ("seed/publications.json", "seed/manifest.json", "data/research.json")
stage = ""
if name == "git":
    if "rev-parse" in args or "ls-remote" in args:
        print("a" * 40)
    elif "clone" in args:
        stage = "clone"
        Path(args[-1]).mkdir()
    elif "archive" in args:
        stage = "archive"
        print("archive stream")
    elif "restore" in args:
        stage = "restore"
        for path in paths:
            Path(path).write_text("baseline")
    elif "diff" in args:
        assert all(Path(path).read_text() == "baseline" for path in paths)
elif name == "python3":
    stage = args[0]
    if stage == "import_research_seed.py":
        sys.stdin.read()
        for path in paths[:2]:
            Path(path).write_text("candidate")
    elif stage == "build_research.py":
        Path(paths[2]).write_text("candidate")
    elif stage == "validate_data.py":
        assert all(Path(path).read_text() == "baseline" for path in paths)
if stage:
    with open("stages", "a") as log:
        log.write(stage + "\\n")
if stage == failure:
    sys.exit(2)
'''
        for failure in ("none", "clone", "archive", "import_research_seed.py", "build_research.py"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for folder in ("bin", "seed", "data", "runner"):
                    (root / folder).mkdir()
                for path in ("seed/publications.json", "seed/manifest.json", "data/research.json"):
                    (root / path).write_text("baseline")
                for name in ("git", "python3", "sleep"):
                    command = root / "bin" / name
                    command.write_text(f"#!{sys.executable}\n" + textwrap.dedent(fake_command))
                    command.chmod(0o755)
                result = subprocess.run(
                    ["bash", "-c", script], cwd=root, capture_output=True, text=True,
                    env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
                         "BASELINE_REVISION": "a" * 40, "RUNNER_TEMP": str(root / "runner"),
                         "GITHUB_OUTPUT": str(root / "output"), "FAIL_STAGE": failure},
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                stages = (root / "stages").read_text().splitlines()
                if failure == "none":
                    self.assertEqual((root / "output").read_text(), "used_fallback=false\n")
                    self.assertNotIn("restore", stages)
                else:
                    self.assertEqual((root / "output").read_text(), "used_fallback=true\n")
                    self.assertEqual(stages[-2:], ["restore", "validate_data.py"])
                    if failure != "build_research.py":
                        self.assertNotIn("build_research.py", stages)
                    for path in (
                        "seed/publications.json", "seed/manifest.json", "data/research.json",
                    ):
                        self.assertEqual((root / path).read_text(), "baseline")

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
            './watchdog.sh "$RELEASE_REVISION" --exact-only',
            "Verify published data freshness",
            "python3 check_freshness.py",
            "SMOKE_OUTCOME:",
            "FRESHNESS_OUTCOME:",
            "Exact production certification failed",
            "Published data freshness failed",
        )

    def test_refresh_dispatch_carries_the_checked_commit_even_with_an_old_event_sha(self):
        script = run_block("refresh.yml", "Dispatch the normal main deployment")
        python = script.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        response = mock.MagicMock()
        response.__enter__.return_value.status = 204
        for revision in ("b" * 40, "main", "", "b" * 39, "$(touch injected)"):
            with self.subTest(revision=revision), mock.patch.dict(os.environ, {
                "API_URL": "https://api.github.com",
                "REPOSITORY": "NavnoorBawa/navnoor-research",
                "GH_TOKEN": "test-token",
                "GITHUB_SHA": "a" * 40,
                "RELEASE_REVISION": revision,
            }), mock.patch("urllib.request.urlopen", return_value=response) as request:
                if revision == "b" * 40:
                    exec(compile(python, "refresh-dispatch", "exec"), {})
                    sent = request.call_args.args[0]
                    self.assertEqual(json.loads(sent.data), {
                        "ref": "main", "inputs": {"release_revision": revision},
                    })
                    self.assertEqual(sent.method, "POST")
                    self.assertEqual(sent.full_url,
                                     "https://api.github.com/repos/NavnoorBawa/"
                                     "navnoor-research/actions/workflows/deploy.yml/dispatches")
                else:
                    with self.assertRaises(SystemExit):
                        exec(compile(python, "refresh-dispatch", "exec"), {})
                    request.assert_not_called()

    def test_requested_release_is_authorized_independently_of_dispatch_event_sha(self):
        script = run_block("deploy.yml", "Validate requested revision against remote main")
        for revision, remote, expected in (
            ("b" * 40, "b" * 40, "true"),
            ("a" * 40, "b" * 40, "false"),
            ("main", "b" * 40, "error"),
            ("b" * 40, "not-a-sha", "error"),
        ):
            with self.subTest(revision=revision, remote=remote):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    for name, body in (
                        ("git", 'printf "%s\\n" "$FAKE_REMOTE"'),
                        ("sleep", "exit 0"),
                    ):
                        executable = root / name
                        executable.write_text("#!/bin/sh\n" + body + "\n")
                        executable.chmod(0o755)
                    output = root / "output"
                    result = subprocess.run(
                        ["bash", "-c", script], capture_output=True, text=True, timeout=10,
                        env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                             "GITHUB_SHA": "a" * 40, "RELEASE_REVISION": revision,
                             "REMOTE_URL": "https://github.com/NavnoorBawa/navnoor-research.git",
                             "FAKE_REMOTE": remote, "GITHUB_OUTPUT": str(output)},
                    )
                    if expected == "error":
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(output.exists())
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(output.read_text(), f"current={expected}\n")

    def test_every_release_stage_uses_the_explicit_authorized_revision(self):
        text = workflow("deploy.yml")
        self.assertIn("RELEASE_REVISION: ${{ inputs.release_revision || github.sha }}", text)
        self.assertNotIn("$GITHUB_SHA", text)
        self.assertEqual(text.count("ref: ${{ env.RELEASE_REVISION }}"), 3)
        self.assertIn("if: needs.resolve.outputs.current == 'true'", text)
        for command in (
            'build_site.py --revision "$RELEASE_REVISION"',
            'validate_release.py --expected-revision "$RELEASE_REVISION"',
            'smoke_test_site.py --expected-revision "$RELEASE_REVISION"',
            './watchdog.sh "$RELEASE_REVISION" --exact-only',
        ):
            self.assertIn(command, text)
        self.assertEqual(text.count('[ "$remote_main" != "$RELEASE_REVISION" ]'), 4)

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
