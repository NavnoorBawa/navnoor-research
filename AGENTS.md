# Repository working agreement

These instructions apply to the entire repository.

## Product boundary

Navnoor Research is a dependency-free Python pipeline and a static site with
exactly three things in it: **Articles** (search over published research
metadata), **News** (checked headlines from reviewed public sources), and
**Discovery** (a name resolved to its articles and headlines).

It is not a broker, quote terminal, portfolio system, or investment
recommendation service. Prefer removing a feature to adding one.

## Required checks

Run before and after a change:

```bash
python3 -m unittest discover -s . -p 'test_*.py' -v
python3 validate_data.py
SITE_OUTPUT_DIR="$(mktemp -d)" SITE_REVISION=local-audit python3 build_site.py
python3 validate_release.py --site "$SITE_OUTPUT_DIR" --expected-revision local-audit
python3 smoke_test_site.py --site "$SITE_OUTPUT_DIR"
rm -r "$SITE_OUTPUT_DIR"
python3 -m py_compile *.py navnoor_research/*.py navnoor_research/adapters/*.py
ruff check .
mypy --cache-dir /tmp/navnoor-research-mypy
git diff --check
```

## Change rules

- Use only the Python 3.9+ standard library at runtime.
- The published research corpus is **read-only**. Never write to it, and never
  read a body, member preview, or parser observation from it.
- A body-derived lead may only be published for an article that is publicly
  readable. For paid or locked articles the subtitle is the only permitted text.
- Never publish a number the data cannot support. If a wordcount describes an
  excerpt, there is no reading time — omit the field rather than estimate it.
- Reader search terms stay in page memory. Never put them in a URL, in storage,
  in a log, or in an upstream request. Adapter queries come from reviewed
  constants only.
- Every adapter must enforce its reviewed host, HTTPS, no redirects, allowed
  fields, byte and time bounds, and atomic last-known-good promotion.
- Do not call delayed or periodically checked data "live". The interface says
  **checked**.
- Do not edit generated `_site/` output; rebuild it.
- Keep the build deterministic. No timestamps, no ordering that depends on a
  set, no randomness. The same inputs and revision must produce identical bytes.
- A release is complete only after exact artifact validation and an exact-live
  smoke check for the same commit.
