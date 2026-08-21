"""The HTML shell.

One page, rendered once at build time. It carries no content of its own beyond
the frame: the article, headline and taxonomy payloads arrive as separate
content-addressed JSON so the shell stays small and cacheable.
"""

from __future__ import annotations

from html import escape

CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "base-uri 'none'; "
    "form-action 'none'"
    # frame-ancestors is deliberately absent: it is ignored when delivered in a
    # meta element, and GitHub Pages already sends X-Frame-Options for the host.
)

DESCRIPTION = (
    "Search published research by keyword, company, ticker or topic, and scan "
    "checked market headlines from reviewed public sources."
)

SEARCH_ICON = (
    '<svg class="search__icon" width="18" height="18" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">'
    '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'
)


def render(assets: dict[str, str], revision: str, article_count: int,
           headline_count: int) -> str:
    """Build the shell. `assets` maps logical names to fingerprinted filenames."""
    css = escape(assets["css"])
    js = escape(assets["js"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta name="description" content="{escape(DESCRIPTION)}">
<meta name="robots" content="index, follow">
<title>Navnoor Research — article search and market news</title>
<link rel="stylesheet" href="{css}">
</head>
<body>
<header class="masthead">
  <div class="shell masthead__inner">
    <a class="brand" href="./">Navnoor Research</a>
    <nav class="tabs" id="tabs" role="tablist" aria-label="Sections">
      <button type="button" class="tab" role="tab" data-tab="articles"
              aria-selected="true">Articles</button>
      <button type="button" class="tab" role="tab" data-tab="news"
              aria-selected="false">News</button>
    </nav>
  </div>
</header>

<main class="shell" id="main">
  <div class="search">
    <label class="search__field">
      <span class="sr-only" hidden>Search</span>
      {SEARCH_ICON}
      <input class="search__input" id="input" type="search" autocomplete="off"
             spellcheck="false" enterkeyhint="search"
             placeholder="Search {article_count} articles by keyword, company, ticker or topic…">
      <kbd class="search__hint" id="hint">/</kbd>
      <button type="button" class="search__clear" id="clear" hidden>Clear</button>
    </label>
  </div>

  <div class="filters">
    <select class="select" id="topicFilter" aria-label="Filter by topic"></select>
    <select class="select" id="accessFilter" aria-label="Filter by access"></select>
    <select class="select" id="sortFilter" aria-label="Sort results"></select>
    <span class="filters__spacer"></span>
    <span class="count" id="count" role="status" aria-live="polite"></span>
  </div>

  <section class="discovery" id="discovery" hidden aria-label="Discovery"></section>

  <noscript>
    <div class="empty">
      <p class="empty__title">Search needs JavaScript</p>
      <p>This page runs its search locally in your browser, so nothing you type
         is ever sent anywhere. That requires JavaScript to be enabled.</p>
    </div>
  </noscript>

  <ul class="results" id="results"></ul>
  <div class="empty" id="empty" hidden></div>
  <button type="button" class="more" id="more" hidden></button>
</main>

<footer class="shell colophon">
  <span>{article_count} articles · {headline_count} checked headlines ·
        <span id="checked-at"></span></span>
  <span>Metadata and links only. Not investment advice.
        Build <code>{escape(revision[:12])}</code></span>
</footer>

<div id="payloads" hidden
     data-articles="{escape(assets['articles'])}"
     data-news="{escape(assets['news'])}"
     data-taxonomy="{escape(assets['taxonomy'])}"></div>
<script src="{js}" defer></script>
</body>
</html>
"""
