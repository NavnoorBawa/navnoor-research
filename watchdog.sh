#!/usr/bin/env bash
# Rebuild current HEAD, check tracked-data freshness, and prove exact production bytes.
set -Eeuo pipefail

PRODUCTION_ORIGIN='https://navnoorbawa.github.io/navnoor-research/'

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <40-character-commit-sha>" >&2
    exit 2
fi

EXPECTED_REVISION=$1
if [[ ! "$EXPECTED_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Expected revision must be an exact lowercase 40-character commit SHA." >&2
    exit 2
fi

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
if [ "$(git rev-parse --verify HEAD)" != "$EXPECTED_REVISION" ]; then
    echo "Watchdog must run from the exact expected revision." >&2
    exit 2
fi

python3 validate_data.py
python3 refresh_companies.py --offline
python3 refresh_news.py --offline
python3 build_site.py --revision "$EXPECTED_REVISION"
python3 validate_release.py --expected-revision "$EXPECTED_REVISION"
python3 smoke_test_site.py --expected-revision "$EXPECTED_REVISION"

# Freshness is operational state, independent of release-byte integrity. A
# recently attempted but degraded source is reported without hiding a valid
# last-known-good release; failure means the scheduled publisher itself is stale.
python3 - <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def instant(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{label} is not a canonical UTC second") from exc
    return parsed.replace(tzinfo=timezone.utc)


def fail(message):
    print(f"::error title=Published data freshness::{message}", file=sys.stderr)
    raise SystemExit(1)


now = datetime.now(timezone.utc)
future = now + timedelta(minutes=10)
seed = json.loads(Path("seed/manifest.json").read_text(encoding="utf-8"))
companies = json.loads(Path("data/companies.json").read_text(encoding="utf-8"))
news = json.loads(Path("data/news.json").read_text(encoding="utf-8"))

try:
    archive_checked = instant(seed["source_snapshot"]["checked_at"], "archive check")
    company_checked = instant(companies["checked_at"], "SEC company check")
except (KeyError, TypeError, ValueError) as exc:
    fail(str(exc))

for label, stamp in (("archive", archive_checked), ("SEC company", company_checked)):
    if stamp > future:
        fail(f"{label} check time is implausibly in the future")
if now - archive_checked > timedelta(hours=36):
    fail("the public research archive has not completed a source check in 36 hours")
if now - company_checked > timedelta(hours=72):
    fail("the SEC company registry has not completed a refresh in 72 hours")

states = news.get("sources")
if not isinstance(states, dict) or not states:
    fail("checked headline source state is missing")
for source_id, state in sorted(states.items()):
    try:
        attempted = instant(state["last_attempt_at"], f"{source_id} last attempt")
    except (KeyError, TypeError, ValueError) as exc:
        fail(str(exc))
    if attempted > future:
        fail(f"{source_id} last attempt is implausibly in the future")
    if now - attempted > timedelta(hours=12):
        fail(f"{source_id} has not been attempted in 12 hours")
    success = state.get("last_success_at")
    status = state.get("status")
    if success is None or status != "ok":
        print(
            f"::warning title=Checked source degraded::{source_id} is {status!r}; "
            "the validated last-known-good release remains exact"
        )
        continue
    try:
        succeeded = instant(success, f"{source_id} last success")
    except ValueError as exc:
        fail(str(exc))
    if succeeded > attempted:
        fail(f"{source_id} last success is later than its last attempt")
    if now - succeeded > timedelta(hours=48):
        fail(f"{source_id} has not succeeded in 48 hours")

print("freshness: scheduled archive, SEC, and headline checks are within policy")
PY

# GitHub Pages can take a bounded interval to expose a just-deployed artifact.
# Poll the small manifest first, then make one full manifest-driven pass over
# every served file after the exact deterministic manifest has arrived.
attempt=1
while [ "$attempt" -le 12 ]; do
    if python3 - <<'PY'
import urllib.error
import urllib.request
from pathlib import Path

url = "https://navnoorbawa.github.io/navnoor-research/release.json"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.URLError(f"redirect refused: {newurl}")


opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
expected = Path("_site/release.json").read_bytes()
with opener.open(url, timeout=20) as response:
    actual = response.read(20_001)
    if response.status != 200 or response.geturl() != url:
        raise SystemExit("served release manifest was not exact HTTP 200")
if len(actual) > 20_000:
    raise SystemExit("served release manifest exceeded the fixed byte ceiling")
if actual != expected:
    raise SystemExit("served release manifest differs from the deterministic rebuild")
print("exact manifest: production matches the deterministic rebuild")
PY
    then
        break
    fi
    if [ "$attempt" -lt 12 ]; then
        echo "Manifest check attempt $attempt failed; retrying in 10 seconds." >&2
        sleep 10
    fi
    attempt=$((attempt + 1))
done

if [ "$attempt" -gt 12 ]; then
    echo "Production did not serve the exact expected manifest after 12 attempts." >&2
    exit 1
fi

python3 smoke_test_site.py \
    --expected-revision "$EXPECTED_REVISION" \
    --url "$PRODUCTION_ORIGIN"
echo "Production release is exact at $EXPECTED_REVISION"
