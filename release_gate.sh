#!/usr/bin/env bash
# Rehearse the complete release gate for one exact committed revision.
set -Eeuo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <40-character-commit-sha>" >&2
    exit 2
fi

REVISION=$1
if [[ ! "$REVISION" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Release revision must be an exact lowercase 40-character commit SHA." >&2
    exit 2
fi

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

resolved_revision=$(git rev-parse --verify "${REVISION}^{commit}")
head_revision=$(git rev-parse --verify HEAD)
if [ "$resolved_revision" != "$REVISION" ] || [ "$head_revision" != "$REVISION" ]; then
    echo "Release gate must run from the exact worktree for $REVISION." >&2
    exit 2
fi

require_clean_revision() {
    if [ "$(git rev-parse --verify HEAD)" != "$REVISION" ] \
        || [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
        echo "Release gate requires an unchanged clean exact-revision worktree." >&2
        exit 2
    fi
}

for tool in python3 ruff mypy; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "Required release tool is unavailable: $tool" >&2
        exit 2
    fi
done

TEMP_ROOT=""
cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ -n "$TEMP_ROOT" ] && [ -d "$TEMP_ROOT" ]; then
        rm -rf -- "$TEMP_ROOT"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/navnoor-research-release.XXXXXX")
MYPY_CACHE_DIR="$TEMP_ROOT/mypy-cache"

require_clean_revision
python3 -m unittest discover -s . -p 'test_*.py' -v
python3 validate_data.py
python3 refresh_companies.py --offline
python3 refresh_news.py --offline
python3 build_site.py --revision "$REVISION"
python3 validate_release.py --expected-revision "$REVISION"
python3 smoke_test_site.py --expected-revision "$REVISION"
python3 -m py_compile ./*.py ./navnoor_research/*.py ./navnoor_research/adapters/*.py
ruff check .
mypy --cache-dir "$MYPY_CACHE_DIR"

for file in ./*.sh; do
    if [ -f "$file" ]; then
        bash -n "$file"
    fi
done

git diff --check
require_clean_revision
echo "Release gate passed for $REVISION"
