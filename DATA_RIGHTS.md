# Data rights and source policy

Last reviewed: 2026-08-20. This is an engineering rights screen, not legal
advice.

## Enabled launch sources

- **Navnoor Research Archive** — metadata-only projection from one exact
  published revision. No article body, member-only preview, parser observation,
  manager inference, position, return, or recommendation is copied.
- **SEC EDGAR** — company/ticker/exchange registry and filing metadata from the
  official SEC JSON interfaces. Requests identify this project and stay well
  below the SEC's published 10 requests/second ceiling.
- **GDELT DOC 2.0** — discovery metadata only: title, publisher URL/domain,
  seen time, language, and source country. No publisher body, snippet, image,
  branding, or GDELT tone score is retained. Every use credits GDELT.
- **Federal Reserve Board RSS** — official headline, link, date, category, and
  brief feed description; no seal or third-party image.
- **CFTC RSS** — official headline, link, date, category, and brief feed
  description; no seal or third-party attachment.
- **Federal Register API** — document metadata with an informational-record
  label and official-edition link where available.

## Optional enrichment

- **U.S. Treasury Fiscal Data** may supply clearly labelled structured macro
  facts at the source's declared cadence.
- **OpenFIGI v3** may enrich SEC-backed identifiers offline. The unauthenticated
  adapter is bounded to the stricter documented five jobs per request and no
  arbitrary user query is transmitted.

## Disabled by default

RBI and SEBI feeds remain disabled until written permission or a documented
rights review resolves caching/reproduction constraints.

## Excluded launch sources

Alpha Vantage, NewsAPI, Yahoo Finance/yfinance, FRED, and NSE are not launch
defaults because their free terms, key requirements, redistribution rules, or
automation limits do not fit this public static product. No unlicensed free
real-time quote feed is used, and the interface says “Checked,” never “Live.”

