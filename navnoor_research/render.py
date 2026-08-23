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


def describe(research_count: int, company_count: int, headline_count: int) -> str:
    """State the exact release counts where they can be regenerated every build."""
    return (
        f"{research_count:,} source-linked research records, "
        f"{company_count:,} SEC company/ticker associations, and "
        f"{headline_count:,} checked headlines from reviewed public sources."
    )


PUBLIC_ORIGIN = "https://navnoorbawa.github.io/navnoor-research/"


def render(
    assets: dict[str, str],
    revision: str,
    research_count: int,
    company_count: int,
    headline_count: int,
    source_count: int,
    source_issue_count: int,
) -> str:
    """Render a small shell; every searchable record stays in fingerprinted JSON."""
    description = describe(research_count, company_count, headline_count)
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
<meta name="theme-color" content="#07131e">
<meta property="og:type" content="website">
<meta property="og:title" content="Navnoor Research">
<meta property="og:description" content="{escape(description)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Navnoor Research">
<meta name="twitter:description" content="{escape(description)}">
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
      <span class="brand__wordmark"><strong>NAVNOOR RESEARCH</strong>
        <span>Independent research archive</span></span>
    </a>
    <div class="masthead__actions">
      <span class="edition">Metadata &amp; provenance</span>
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

<section class="index-bar" aria-label="Archive status">
  <div class="shell index-bar__inner">
    <dl class="market-strip">
      <div><dt>Research</dt><dd><data value="{research_count}">{research_count:,}</data></dd></div>
      <div><dt>SEC associations</dt><dd>
        <data value="{company_count}">{company_count:,}</data></dd></div>
      <div><dt>Checked headlines</dt><dd>
        <data value="{headline_count}">{headline_count:,}</data></dd></div>
      <div><dt>Source coverage</dt><dd>
        {source_issue_count} / {source_count} flagged</dd></div>
    </dl>
  </div>
</section>

<main class="main" id="main" tabindex="-1">
  <section class="hero" aria-labelledby="page-title">
    <div class="shell hero__inner">
      <div class="intro__layout">
        <div class="intro">
          <p class="eyebrow">Research archive</p>
          <h1 id="page-title">Search</h1>
          <p class="lede" id="view-description">
            Search publication metadata, SEC company and ticker associations,
            and checked source headlines. Queries remain local to this page.
          </p>
        </div>
      </div>

      <section class="search-panel" aria-label="Search controls">
        <div class="search-panel__head">
          <label class="search-label" for="query">Search</label>
          <span class="search-shortcut" aria-hidden="true"><kbd>/</kbd> to focus</span>
        </div>
        <div class="search-row">
          <input id="query" class="search-input" type="search" autocomplete="off"
                 autocapitalize="off" spellcheck="false" enterkeyhint="search"
                 aria-keyshortcuts="/" aria-describedby="search-privacy search-scope"
                 placeholder="Issuer, $ticker, fund, regulator, or thesis">
          <button type="button" class="clear-button" id="clear" hidden>Clear</button>
        </div>
        <p class="privacy-note" id="search-privacy">
          Private by design: your query stays in this page.
          It is never sent, stored, logged, or added to the URL.
        </p>
        <p class="search-scope" id="search-scope">
          Coverage: ticker, issuer, fund, regulator, and topic terms.
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
      <span class="result-count" id="result-count" role="status"
            aria-live="polite" aria-atomic="true"></span>
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
      <strong>NAVNOOR RESEARCH</strong>
      <span>Independent research archive</span>
    </div>
    <p class="colophon__limits">Metadata and source links only ·
       No quotes, holdings, scores, or investment recommendations</p>
    <p class="colophon__release"><span>Local-query architecture</span>
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
