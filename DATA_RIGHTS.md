# Data rights and source policy

Last reviewed: 2026-08-23. This is an engineering rights screen, not legal
advice.

`config/source_rights.json` is the executable source matrix. Validation fails
if its source IDs, adapter types, request/link hosts, or field allowlists drift
from the adapters described below.

## Enabled sources

- **Navnoor Research Archive** — a metadata-only seed imported from one exact
  Git revision. The importer materialises only access, publication identity,
  source, title, subtitle, date, slug, canonical link, and alternate public
  links. It lexically skips all other article JSON values. No body, member
  preview, parser observation, position, holding, return, or recommendation is
  read into the new product.
- **SEC EDGAR** — one fixed request to the official
  [company/ticker/exchange association file](https://www.sec.gov/files/company_tickers_exchange.json)
  at `www.sec.gov`. The retained fields are a derived stable
  identity, zero-padded CIK, ticker, exchange, company name, and canonical SEC
  browse link. No filing or filing body is requested. The client identifies the
  project and makes no browser-side SEC request. This is a periodically updated
  association dataset, not an SEC listing registry; the SEC does not guarantee
  its accuracy or scope, as explained in its
  [EDGAR data documentation](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).
- **[GDELT Project](https://www.gdeltproject.org/) DOC 2.0** — discovery
  metadata from one fixed market-news query:
  headline title, publisher URL/domain, seen time, language, and source country.
  No publisher body, snippet, image, branding, or tone score is retained. The
  public row labels the publisher separately and links its GDELT discovery
  credit as required by the project's
  [Terms of Use](https://www.gdeltproject.org/about.html). Publisher domains are
  validated against their own canonical URLs, not treated as pre-approved
  editorial partners.
- **Federal Reserve Board RSS** — the official headline, link, publication
  time, category, and feed description may be read. Only headline/link/time and
  deterministic topic/entity classification are published; no seal, image, or
  attachment is copied.

## Reviewed but disabled

- **CFTC RSS** — its metadata fields and official host are reviewed, but the
  adapter remains disabled because the official endpoint did not present a
  certificate chain that the verified standard-library client could
  authenticate during the 2026-08-23 launch audit. TLS verification is not
  bypassed. Enabling this source requires a successful verified fetch and a new
  recorded review.

## Excluded product categories

There is no quote or recommendation feed. Alpha Vantage, NewsAPI, Yahoo
Finance/yfinance, FRED, NSE, social feeds, broker data, and similar sources are
not launch inputs because their key, redistribution, automation, or product-fit
constraints do not match this static public index. No browser query is ever
forwarded to a source.

Operational availability is separate from rights approval. Market News shows
each enabled source's last attempt, last success, status, and retained count;
an unavailable source is labelled as failed rather than described as current
or live.
