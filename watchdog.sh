#!/usr/bin/env bash
# Rebuild current HEAD and prove exact production bytes before checking freshness.
set -Eeuo pipefail

PRODUCTION_ORIGIN='https://navnoorbawa.github.io/navnoor-research/'

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage: $0 <40-character-commit-sha> [--exact-only]" >&2
    exit 2
fi

EXPECTED_REVISION=$1
MODE=${2:-full}
if [[ ! "$EXPECTED_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Expected revision must be an exact lowercase 40-character commit SHA." >&2
    exit 2
fi
if [ "$MODE" != 'full' ] && [ "$MODE" != '--exact-only' ]; then
    echo "Optional watchdog mode must be --exact-only." >&2
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

# Operational freshness is independent of release-byte integrity. Run it only
# after production has been proved exact so staleness cannot mask live drift.
if [ "$MODE" = 'full' ]; then
    python3 check_freshness.py
fi
