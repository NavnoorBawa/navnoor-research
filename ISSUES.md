# Issue log

Last updated: 2026-08-26

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
  forced-colors, light, and print modes have explicit treatments.
- **Verification:** `test_build_site.py`, `test_client_runtime.py`,
  `validate_release.py`, the full release suite, and exact local HTTP smoke
  enforce the premium shell, accessible names/status, responsive modes, and
  unchanged privacy/data boundaries.

### NR-011 — The first premium pass read as editorial luxury, not an investment desk

- **Severity:** P1
- **Evidence:** Direct product feedback found that the oversized serif hero,
  warm-paper and copper palette, floating search-card shadow, decorative
  monograms, and narrative result rows still resembled a premium newsletter.
  They delayed the archive, weakened column alignment, and did not communicate
  the density, provenance, and operational precision expected by institutional
  allocators and hedge-fund research teams.
- **Resolution:** Replaced the editorial language with a calm allocator-grade
  research portal: a navy masthead, light archival workspace, exact-count
  ledger, restrained sans and mono typography, compact local search, ruled
  research, news, and issuer records, a semantic entity brief,
  machine-readable source health, and a provenance footer. Removed the
  floating card, display serif, gold/copper treatment, decorative profile art,
  rounded badges, hover movement, faux-terminal labels, ornamental status dot,
  and unsupported query-syntax claim. The result grid now avoids a compressed
  news rail, source health adapts to the number of sources, and all public type
  remains at least 11px. Search groups expose explicit incremental continuation
  instead of silently stopping at eight records, and source exceptions appear
  both in the top ledger and beside every Search view news group. Archive ledger
  cells stack their labels and values from the 1240px breakpoint to prevent
  tablet and narrow-screen collisions.
  Refreshed the social card as a quiet factual title plate without invented
  market, AUM, holding, performance, or recommendation data; its reviewed bytes
  are bound to the exact three counts printed in the card, so a changing dataset
  fails closed instead of publishing stale figures.
- **Verification:** Release validation now enforces exact navigation and metric
  values, complete CSS variables, measured text and control-boundary contrast,
  320px index-rail containment, semantic metric/check-time markup, unmodified
  search shortcuts, issuer-specific SEC labels, one-column print output,
  forced-colors, reduced motion, count-bound social-card facts, collision-free
  mobile metrics, and the unchanged local-query privacy boundary.

## Remediation in progress

### NR-012 — Cross-post provenance stalled every scheduled checked-data refresh

- **Severity:** P1
- **Evidence:** Scheduled refresh runs `32888738396`, `32903926227`,
  `32921917030`, `32930107289`, `32943221489`, and `32957529464` all rejected
  the same valid archive with
  `seed source check 'medium' newest publication is inconsistent`. The importer
  required exact equality between Medium's pre-deduplication discovery edge and
  the newest row retained canonically as Medium. A newer Medium publication had
  correctly been collapsed into its canonical Substack row, so the scheduled
  job stopped before recording checked-headline attempts. Watchdog run
  `32932139824` and `32950938785` then truthfully reported that checked-headline
  attempts were older than 12 hours. The first monitor named Federal Reserve
  only because its fail-fast loop encountered that source first; exact live
  bytes were not checked in that run even though an independent nine-file
  comparison later proved the deployed `7cf6c3d` release exact.
- **Resolution:** Preserve the exact per-adapter discovery timestamp and apply
  the archive's ordering contract: it may be newer than that source's retained
  canonical rows after cross-post deduplication, but it may not predate them.
  Accept the producer's two publishable source states (`ok` and `degraded`) and
  continue independent SEC and checked-headline refreshes from the validated
  prior seed when archive checkout, import, or projection fails. Restore and
  revalidate the exact three-file baseline before continuing, retry archive
  acquisition and revision proof, and remove the scheduled heartbeat's
  redundant PyPI-backed static-analysis dependency; CI and deployment retain
  those mandatory gates. The 36-hour archive gate still fails closed if the
  fallback persists.
  Split exact-live verification from freshness, run both even when one fails,
  reconcile both against current `main`, and aggregate all stale clocks rather
  than exiting on the alphabetically first headline source.
  Add a regression fixture for a newest Medium discovery retained canonically
  as Substack, plus a negative case proving stale source provenance still fails
  closed. Keep the freshness watchdog and its attempt-age threshold intact.
- **Verification:** The pre-change 180-test baseline passed against the older
  stored seed. The repaired consumer accepted exact upstream revision
  `82307a0f490c05411c4454421953b2f1199a8a55`, imported 583 metadata-only
  publications, refreshed 10,388 SEC associations and 121 retained headlines,
  and recorded a current successful Federal Reserve attempt. All 194 tests,
  tracked-data validation, offline source validation, deterministic build,
  release validation, local HTTP smoke, Python syntax, Ruff, mypy, shell syntax,
  workflow YAML parsing, freshness policy, and diff checks pass. Hosted refresh,
  exact deployment, and independent watchdog evidence remain pending before
  this issue moves to Resolved.

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
