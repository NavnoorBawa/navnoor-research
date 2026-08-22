# Repository working agreement

These instructions apply to the entire repository.

## Product and architecture

Navnoor Research is a dependency-free Python data pipeline and a static GitHub
Pages application with exactly three public destinations: **Search**,
**Research**, and **Market News**. Search resolves reviewed entity aliases and
an independent SEC company/ticker registry entirely in the browser. Research
publishes source-linked article metadata. Market News publishes checked
headline metadata and per-source check state.

It is not a broker, quote terminal, portfolio system, recommendation engine, or
article mirror. There is no reader-query API, telemetry endpoint, or browser
request to a source adapter.

The tracked pipeline inputs are `seed/*.json`, `data/*.json`, and
`config/*.json`. `build_site.py` validates them and generates the ignored
`_site/` artifact with content-addressed data and assets plus a closed-set
release manifest.

## Required local checks

Run the full suite before and after a change:

```bash
python3 -m unittest discover -s . -p 'test_*.py' -v
```

Validate every tracked input and the two stored network snapshots offline:

```bash
python3 validate_data.py
python3 refresh_companies.py --offline
python3 refresh_news.py --offline
```

Build and validate the fixed generated site:

```bash
python3 build_site.py --revision local-audit
python3 validate_release.py --expected-revision local-audit
python3 smoke_test_site.py --expected-revision local-audit
```

Lint and syntax-check the dependency-free codebase:

```bash
python3 -m py_compile ./*.py ./navnoor_research/*.py ./navnoor_research/adapters/*.py
ruff check .
mypy --cache-dir /tmp/navnoor-research-mypy
for file in ./*.sh; do bash -n "$file"; done
git diff --check
```

Before updating remote `main`, commit the exact release and run:

```bash
./release_gate.sh "$(git rev-parse HEAD)"
```

## Change rules

- Preserve the standard-library-only Python 3.9+ runtime and deterministic
  static architecture.
- Import the archive only through a bounded `git archive` stream for one exact
  40-character revision. Never add a corpus path override.
- The seed importer may materialise only its reviewed metadata allowlist. It
  must lexically skip article bodies, member previews, parser observations,
  positions, returns, recommendations, and every other unreviewed JSON value.
- Restricted publication text is limited to the reviewed title and subtitle.
  Never infer or invent a summary, reading time, position, holding, return,
  confidence score, exposure, or recommendation.
- Reader queries and filters stay in page memory. Never put them in a URL,
  storage, log, telemetry event, or upstream request.
- Every network adapter uses a fixed reviewed request, verified HTTPS, no
  redirects or ambient proxies, an exact host and field allowlist, byte/time
  bounds, strict parsing, and atomic last-known-good promotion.
- Call delayed or periodically checked data **checked**, never live. Display a
  source failure and its last-success state rather than implying freshness.
- Do not hand-edit `_site/`; rebuild it from `build_site.py`. The fixed output
  and staging paths must remain non-configurable and symlink-safe.
- Keep `ISSUES.md` current with severity, evidence, resolution, and
  verification. An unresolved launch-safety decision is a blocker.
- A push is not a release until the deployment workflow validates the exact
  artifact and production serves every manifest-listed byte for that same
  commit. Use `watchdog.sh` for the independent exact-live and freshness check.
