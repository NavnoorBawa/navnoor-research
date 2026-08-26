# Navnoor Research

**Search the research. Check the market news. Start from a name.**

Navnoor Research is a small public-source research index with exactly three
destinations:

- **Search** — discover published research, checked headlines, and SEC-backed
  company/ticker associations from a company, ticker, fund, regulator, index,
  asset, or topic.
- **Research** — search and filter every source-linked publication record by
  topic and access state.
- **Market News** — scan retained headline metadata from reviewed public
  sources with publisher, discovery attribution, and an honest status for each
  scheduled source check.

GDELT-discovered rows and source status link their credit to the
[GDELT Project](https://www.gdeltproject.org/), consistent with its
[Terms of Use](https://www.gdeltproject.org/about.html). The SEC company file is
a periodically updated set of company/name/ticker/exchange associations, not an
SEC listing registry; see the SEC's
[EDGAR data documentation](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

It provides no quote, portfolio, holding, score, target, or investment
recommendation. A bare ticker such as `NVDA` produces a company suggestion;
`$NVDA` or `ticker:NVDA` explicitly scopes the result set. Reviewed aliases
such as `IWM`, `AI`, and `SEC` resolve to their corresponding research entity.

Search runs entirely in the page over four content-addressed, same-origin data
files. There is no account, cookie, analytics, telemetry, third-party script,
remote font, or backend that receives the query.

## Architecture

The dependency-free Python 3.9+ pipeline produces a deterministic GitHub Pages
bundle. Every input is validated before build; every public file is listed by
size and SHA-256 in `release.json`; the browser verifies each data asset against
the digest embedded in its filename before installing any of them.

```text
seed/publications.json   rights-safe exact-revision archive projection
seed/manifest.json       source revision, input digests, counts, check state
data/research.json       deterministic searchable publication metadata
data/companies.json      last-known-good SEC company/ticker associations
data/news.json           last-known-good checked headline metadata and states
config/*.json            reviewed entity, topic, and source-rights tables
_site/                   ignored deterministic Pages bundle
```

The archive seed is independent from the new application at runtime: it is a
tracked, rights-bounded transaction imported from one exact archive commit.
The production build never reaches into another checkout and never reads an
article body.

## Refreshing tracked data

Import one exact local archive revision through standard input, then rebuild
the research projection:

```bash
ARCHIVE_REVISION="$(git -C '../substack trades' rev-parse HEAD)"
git -C '../substack trades' archive "$ARCHIVE_REVISION" \
  articles_index.json trades_extracted.json snapshot_manifest.json \
  | python3 import_research_seed.py --revision "$ARCHIVE_REVISION" --write
python3 build_research.py
```

Refresh the independent SEC registry and checked news sources:

```bash
python3 refresh_companies.py
python3 refresh_news.py
```

Each network refresh validates the previous snapshot first, uses fixed reviewed
requests, and promotes a complete replacement atomically. A failed response
does not replace valid last-known-good data. Offline validation never uses the
network:

```bash
python3 refresh_companies.py --offline
python3 refresh_news.py --offline
```

## Building and checking

```bash
python3 -m unittest discover -s . -p 'test_*.py' -v
python3 validate_data.py
python3 build_site.py --revision local-audit
python3 validate_release.py --expected-revision local-audit
python3 smoke_test_site.py --expected-revision local-audit
python3 -m http.server 8000 --directory _site
```

For an exact committed release, run `./release_gate.sh "$(git rev-parse HEAD)"`.
After deployment, `./watchdog.sh "$(git rev-parse HEAD)"` rebuilds the same
revision, compares every served release byte, and only then checks source
freshness. Automation runs the exact-byte and freshness gates as separate steps
and reconciles both against current `main`, so either failure stays visible and
neither can short-circuit the other.

On macOS, the watchdog uses the OS-maintained `/etc/ssl/cert.pem` trust bundle
when a Python.org interpreter is on `PATH` without its optional CA bootstrap.
HTTPS verification remains mandatory; the fallback never disables TLS checks.

The archive manifest records each adapter's newest discovered publication
before cross-source deduplication. That timestamp can be newer than the newest
row retained canonically under the same source when, for example, a Medium
cross-post is retained as Substack with Medium as an alternate URL. The seed
importer preserves that exact provenance and verifies that it does not predate
the source's retained canonical rows.

If the watchdog reports that a checked-headline source has not been attempted,
inspect the latest **Refresh Checked Data** run first. The watchdog is a
downstream alarm: it intentionally stays red when the scheduled publisher has
stopped before recording source attempts, even if the last deployed bytes are
still exact.

Archive import, SEC refresh, and checked-headline refresh have separate
last-known-good boundaries. An archive fetch or import failure retains the
previous validated seed while SEC and headline checks continue; the independent
36-hour archive freshness gate still turns red if that upstream failure
persists. A valid archive source state may be `ok` or `degraded`, matching the
producer's publishable contract; an unknown or failed state remains rejected.

The scheduled data workflow is standard-library-only and does not install
developer tools from PyPI. Ruff and mypy remain mandatory in CI, deployment,
and the exact local release gate; they do not sit in front of the three-hour
source-attempt heartbeat for code that has already reached `main`.

Fresh headline attempts older than 12 hours are a hard scheduler failure.
Recently attempted `error` or `partial` adapters remain visible warnings and
retain their validated last-known-good metadata; persistence beyond 48 hours is
escalated in the warning text but remains non-blocking unless the fixed source
policy is explicitly changed.

## Publication boundary

Research records contain only title, canonical publisher link, source, real
publication time, access state, deterministic topic/entity references, and an
optional reviewed subtitle exposed as `summary`. Publisher bodies, member
previews, images, branding, parser observations, word counts, positions,
returns, holdings, and recommendations are never included. Restricted records
receive no body-derived text and no reading-time estimate.

Market News stores checked headline metadata, never an article body or snippet.
Headlines framed as live coverage, a price target, rating change, or investment
recommendation are excluded. The interface distinguishes the actual publisher
domain from the source used to discover the metadata.

See [DATA_RIGHTS.md](DATA_RIGHTS.md), [PRIVACY.md](PRIVACY.md), and
[ISSUES.md](ISSUES.md).
