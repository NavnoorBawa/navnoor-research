# Issue log

Last updated: 2026-08-23

## Resolved

### NR-001 — Restricted source material crossed the original import boundary

- **Severity:** P0
- **Evidence:** The prototype importer could consume path-selected corpus
  records containing body-derived leads, member-preview metadata, and excerpt
  word counts. One restricted Nomura record exposed a body-derived lead and an
  unsupported reading-time estimate.
- **Resolution:** Replaced the path-bearing importer with an exact-revision,
  bounded Git-archive transaction. Its selective parser materialises only the
  reviewed seed allowlist and lexically skips every unreviewed JSON value.
  Removed the legacy tracked article payload and all reading-time fields.
- **Verification:** `test_seed.py`, `test_corpus.py`, `test_validation.py`, and
  `validate_data.py` prove exact projection, restricted subtitle-only text, and
  the absence of prohibited fields from seed, research, and release data.

### NR-002 — Prototype information architecture and claims missed the product

- **Severity:** P1
- **Evidence:** The prototype exposed Articles/News/Discovery labels, incomplete
  tab semantics, unstable search naming, mobile overflow, and live/target/rating
  language that this product cannot substantiate.
- **Resolution:** Rebuilt the shell around exactly Search, Research, and Market
  News; ordinary pressed-state buttons; one Search heading; visible privacy and
  limitation copy; 320-pixel responsive layout; complete focus states; and
  checked-source language. Prohibited headline formats are filtered both in the
  pipeline and in the browser payload validator.
- **Verification:** `test_build_site.py`, `test_client_runtime.py`, and
  `validate_release.py` enforce the public labels, accessibility/privacy
  boundary, runtime alias/ticker behavior, and prohibited-claim filter.

### NR-003 — Network, XML, storage, and release boundaries were too permissive

- **Severity:** P1
- **Evidence:** The prototype accepted redirects and ambient proxies, lacked
  complete URL/content/size checks, could miss a UTF-16 XML entity declaration,
  accepted structurally weak snapshots, and allowed caller-selected build or
  corpus paths.
- **Resolution:** Added fixed reviewed requests, verified TLS, no redirects or
  proxies, canonical URL and content checks, byte/time bounds, strict UTF-8/XML
  and JSON parsing, exact aggregate/state validation, atomic durable writes,
  fixed symlink-safe paths, and closed-set release manifests.
- **Verification:** Adapter, seed, news-store, manifest, build, and release tests
  cover malformed encodings, redirects, host drift, duplicates, aggregates,
  symlinks, byte ceilings, and last-known-good retention.

### NR-004 — Ticker discovery depended on the publication corpus

- **Severity:** P1
- **Evidence:** The prototype had no independent company/ticker reference and
  could silently interpret a bare ticker as a scoped research query.
- **Resolution:** Added a daily fixed SEC company/ticker association snapshot.
  Bare text produces explicit suggestions; `$TICKER` or `ticker:TICKER` scopes
  only after a registry match.
- **Verification:** `test_sec.py`, `test_client_runtime.py`, offline company
  validation, and release validation cover exact parsing, canonical ordering,
  NVDA discovery, and the complete compact browser projection.

### NR-007 — Exact deployment and remote-smoke boundaries had gaps

- **Severity:** P1
- **Evidence:** The Pages artifact uploader did not opt into hidden files even
  though `.nojekyll` is part of the exact release manifest; the remote smoke
  test could iterate unvalidated manifest paths; and the RSS ceiling counted
  only projected records rather than every raw enumerated item.
- **Resolution:** Enabled hidden-file upload for deploy and rollback, moved the
  full release-envelope/path validation ahead of every remote asset request,
  and enforce the RSS ceiling before item projection.
- **Verification:** `test_manifest.py`, `test_smoke_test_site.py`, and
  `test_adapters.py` cover unsafe/duplicate paths, malicious remote envelopes,
  and oversized raw feeds. Both workflow files pass strict YAML parsing.

### NR-008 — Search interactions could produce misleading or inert results

- **Severity:** P1
- **Evidence:** Topic buttons in Search set a hidden filter that Search then
  cleared, Search could inherit a hidden dedicated-view sort, valid source ISO
  timestamps with fractional seconds were rejected, and several target/rating
  headline phrasings passed the initial denylist.
- **Resolution:** Search topic clicks now become a visible local query, Search
  chooses its own deterministic ordering without mutating dedicated views, the
  client validates real dates and source timestamp variants, and the shared
  server/client denylist covers the audited target, rating, upgrade/downgrade,
  pick, and recommendation phrasings.
- **Verification:** `test_client_runtime.py`, `test_newsstore.py`, and the exact
  built-payload runtime check exercise every corrected behavior.

### NR-009 — Source status, credit, and SEC wording were incomplete

- **Severity:** P1
- **Evidence:** An all-source refresh failure retained old items but discarded
  the new failed-attempt states; GDELT credit was plain text despite its linked
  citation requirement; and interface copy called an SEC association file a
  listing registry.
- **Resolution:** Failed refreshes now atomically retain exact checked items
  while publishing the new error attempts, every GDELT row and source-status
  card links the fixed official project origin, and copy consistently describes
  the SEC file as company/ticker associations with its documented limitation.
- **Verification:** `test_refresh_news.py`, `test_client_runtime.py`,
  `validate_release.py`, and the source-rights documentation enforce the
  corrected operational and disclosure contracts.

### NR-010 — The launch interface lacked an institutional visual hierarchy

- **Severity:** P1
- **Evidence:** The initial shell relied on generic rounded controls, a filled
  tab treatment, undifferentiated full-width lists, and weak separation between
  publication dates, titles, source metadata, entity context, and operational
  source status. Small muted text and form boundaries also missed the intended
  contrast margin.
- **Resolution:** Rebuilt the interface as a system-font editorial research
  ledger: midnight masthead and hero, warm paper workspace, restrained brass
  accent, visible archive coverage, command-style local search, responsive
  overview grid, date-led result rows, a high-contrast entity brief, operational
  source rail, and a structured colophon. Search announcements are now visible
  outside hidden filters; filter focus is retained; the final pagination action
  has a deterministic focus successor; and mobile, reduced-motion,
  forced-colors, dark, and print modes have explicit treatments.
- **Verification:** `test_build_site.py`, `test_client_runtime.py`,
  `validate_release.py`, the full release suite, and exact local HTTP smoke
  enforce the premium shell, accessible names/status, responsive modes, and
  unchanged privacy/data boundaries.

## Open operational issues

### NR-005 — CFTC feed is unavailable through verified TLS

- **Severity:** P2 (non-blocking; source disabled)
- **Evidence:** The official CFTC RSS endpoint failed certificate-chain
  verification in the dependency-free standard-library client on 2026-08-23.
- **Current handling:** The reviewed source remains explicitly disabled. No TLS
  bypass, alternate host, or stale CFTC item is published.
- **Resolution condition:** Record a successful verified fetch from the exact
  reviewed endpoint, rerun the full source review, and enable it in the fixed
  matrix with tests.

### NR-006 — GDELT launch check is degraded

- **Severity:** P2 (visible and non-blocking)
- **Evidence:** The launch refresh received HTTP 429 from the fixed GDELT DOC
  request; there is not yet a successful retained GDELT snapshot.
- **Current handling:** Market News exposes the GDELT source as `error`, with no
  invented success time or headline. The validated Federal Reserve snapshot is
  retained independently.
- **Resolution condition:** A scheduled bounded refresh completes successfully
  and the promoted source state records the exact attempt/success time.
