"""Deterministic HTML shell for the three-surface public product."""

from __future__ import annotations

from html import escape

CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self'; "
    "font-src 'none'; "
    "object-src 'none'; "
    "frame-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

DESCRIPTION = (
    "Search source-linked research metadata, discover SEC company/ticker associations, "
    "and scan checked market news from reviewed public sources."
)
PUBLIC_ORIGIN = "https://navnoorbawa.github.io/navnoor-research/"


def render(
    assets: dict[str, str],
    revision: str,
    research_count: int,
    company_count: int,
    headline_count: int,
) -> str:
    """Render a small shell; every searchable record stays in fingerprinted JSON."""
    og = ""
    if assets.get("og"):
        og_name = escape(assets["og"])
        og = (
            f'<meta property="og:image" content="{PUBLIC_ORIGIN}{og_name}">\n'
            f'<meta name="twitter:image" content="{PUBLIC_ORIGIN}{og_name}">\n'
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="no-referrer">
<meta name="description" content="{escape(DESCRIPTION)}">
<meta name="robots" content="index, follow">
<meta name="theme-color" content="#0b1b29">
<meta property="og:type" content="website">
<meta property="og:title" content="Navnoor Research">
<meta property="og:description" content="{escape(DESCRIPTION)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Navnoor Research">
<meta name="twitter:description" content="{escape(DESCRIPTION)}">
<meta property="og:url" content="{PUBLIC_ORIGIN}">
<link rel="canonical" href="{PUBLIC_ORIGIN}">
{og}<title>Navnoor Research — Search, Research, Market News</title>
<link rel="stylesheet" href="{escape(assets['css'])}">
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="masthead">
  <div class="shell masthead__inner">
    <a class="brand" href="./" aria-label="Navnoor Research home">
      <span class="brand__mark" aria-hidden="true">NR</span>
      <span class="brand__wordmark"><strong>Navnoor</strong><span>Research</span></span>
    </a>
    <div class="masthead__actions">
      <span class="edition">Independent public index</span>
      <nav class="views" aria-label="Primary">
        <button type="button" class="view-button" data-view="search"
                aria-pressed="true">Search</button>
        <button type="button" class="view-button" data-view="research"
                aria-pressed="false">Research</button>
        <button type="button" class="view-button" data-view="news"
                aria-pressed="false">Market News</button>
      </nav>
    </div>
  </div>
</header>

<main class="main" id="main" tabindex="-1">
  <section class="hero" aria-labelledby="page-title">
    <div class="shell hero__inner">
      <div class="intro__layout">
        <div class="intro">
          <p class="eyebrow">Source-linked intelligence</p>
          <h1 id="page-title">Search</h1>
          <p class="lede" id="view-description">
            Find research, SEC company/ticker associations, and checked market news
            from one local search.
          </p>
        </div>
        <aside class="coverage" aria-label="Archive coverage">
          <p class="coverage__label">Current index</p>
          <dl>
            <div><dt>Research</dt><dd>{research_count:,}</dd></div>
            <div><dt>Companies</dt><dd>{company_count:,}</dd></div>
            <div><dt>Headlines</dt><dd>{headline_count:,}</dd></div>
          </dl>
        </aside>
      </div>

      <section class="search-panel" aria-label="Search controls">
        <div class="search-panel__head">
          <label class="search-label" for="query">Search</label>
          <span class="search-shortcut" aria-hidden="true"><kbd>/</kbd> to focus</span>
        </div>
        <div class="search-row">
          <input id="query" class="search-input" type="search" autocomplete="off"
                 autocapitalize="off" spellcheck="false" enterkeyhint="search"
                 placeholder="Company, ticker, fund, regulator, or topic">
          <button type="button" class="clear-button" id="clear" hidden>Clear</button>
        </div>
        <p class="privacy-note">
          <span class="privacy-dot" aria-hidden="true"></span>
          Private by design: your query stays in this page.
          It is never sent, stored, logged, or added to the URL.
        </p>
      </section>
    </div>
  </section>

  <div class="shell workspace">
    <div class="toolbar">
      <div class="filters" id="filters" hidden>
        <label>Topic <select id="topic-filter"></select></label>
        <label id="access-wrap">Access <select id="access-filter"></select></label>
        <label>Order <select id="sort-filter"></select></label>
      </div>
      <span class="result-count" id="result-count" role="status" aria-live="polite"></span>
    </div>

    <div class="load-status" id="load-status" role="status" aria-live="polite" hidden>
      Verifying this release…
    </div>
    <noscript>
      <div class="notice"><h2>JavaScript is required</h2>
        <p>Search runs only in your browser over this release’s static,
           source-linked metadata.</p>
      </div>
    </noscript>

    <section class="profile" id="profile" hidden aria-labelledby="profile-title"></section>
    <section id="content" aria-labelledby="results-heading">
      <h2 class="results-heading" id="results-heading" tabindex="-1">Results</h2>
      <div id="results"></div>
    </section>
  </div>
</main>

<footer class="footer">
  <div class="shell colophon">
    <div class="colophon__identity">
      <span class="colophon__mark" aria-hidden="true">NR</span>
      <div><strong>Navnoor Research</strong>
        <p>{research_count:,} research records ·
           {company_count:,} company/ticker associations ·
           {headline_count:,} checked headlines</p>
      </div>
    </div>
    <p class="colophon__limits">Metadata and source links only.<br>
       No quotes, holdings, scores, or investment recommendations.<br>
       Build <code>{escape(revision[:12])}</code></p>
  </div>
</footer>

<div id="payloads" hidden
     data-research="{escape(assets['research'])}"
     data-companies="{escape(assets['companies'])}"
     data-news="{escape(assets['news'])}"
     data-taxonomy="{escape(assets['taxonomy'])}"></div>
<script src="{escape(assets['js'])}" defer></script>
</body>
</html>
"""
