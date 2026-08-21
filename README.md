# Navnoor Research

**Search the research. Scan the news. Start from a name.**

A fast, source-linked research index built for people who open a page, type a
name, and want the answer before they have finished thinking about it.

Three things, done properly:

- **Articles** — every published piece, searchable by keyword, company, ticker,
  fund, regulator or topic, with the date, access and topic on the row.
- **News** — checked headlines from reviewed public sources, each carrying its
  attribution, its timestamp and a link straight to the publisher.
- **Discovery** — type a name and the page tells you what it is and how much
  there is: *Jane Street · fund · 14 articles · 0 headlines*.

There is no account, cookie, telemetry, remote script, remote font or backend
that receives what you type. Search runs in the page, over data already loaded.

## How it is built

A dependency-free Python 3.9+ pipeline produces a static bundle. Source records
are validated before the build; the build emits an HTML shell, fingerprinted
same-origin CSS and JavaScript, content-addressed JSON, and a release manifest
binding every public byte to one Git revision.

The whole site is about 300 KB, of which the shell is 3 KB.

```
config/*.json        reviewed entity, topic and source-rights tables
data/articles.json   normalised article metadata      (import_articles.py)
data/news.json       checked headlines, last known good (refresh_news.py)
_site/               the built bundle                 (build_site.py)
```

News refreshes are scheduled pipeline jobs, never browser requests. Every
adapter enforces an HTTPS host allowlist, refuses redirects, caps bytes and
time, bounds retries, parses XML with entity expansion refused, keeps only
allow-listed fields, and promotes a snapshot atomically so a bad network day
leaves the previous one intact.

## Running it

```bash
python3 import_articles.py                 # corpus -> data/articles.json
python3 refresh_news.py                    # reviewed sources -> data/news.json
python3 validate_data.py                   # shape, references, rights rules
SITE_REVISION=$(git rev-parse HEAD) python3 build_site.py
python3 -m http.server 8000 --directory _site
```

`import_articles.py` reads the corpus read-only. Point it somewhere else with
`--corpus DIR` or `CORPUS_DIR`.

## Checks

```bash
python3 -m unittest discover -s . -p 'test_*.py' -v
python3 validate_data.py
SITE_OUTPUT_DIR="$(mktemp -d)" SITE_REVISION=local-audit python3 build_site.py
python3 validate_release.py --site "$SITE_OUTPUT_DIR" --expected-revision local-audit
python3 smoke_test_site.py --site "$SITE_OUTPUT_DIR"
rm -r "$SITE_OUTPUT_DIR"
ruff check .
mypy --cache-dir /tmp/navnoor-research-mypy
```

## What the metadata can and cannot say

The catalogue is only as good as the corpus behind it, and the honest picture
for 559 articles is:

| Field | Coverage | Why |
|---|---|---|
| Title, link, date, source | 100% | present for every record |
| Access (free / paid) | 100% | six inconsistent audience strings collapsed to three |
| Topic | 82% | keyword and entity rules; the rest fall back to *General* |
| Entities | 67% | matched against the reviewed alias table |
| Summary | 41% | subtitle, or the lead for publicly readable articles |
| Reading time | 4% | **only** where the corpus holds a complete body |

Reading time is deliberately sparse. Most records store an excerpt, and an
excerpt's word count describes the teaser, not the article — printing it would
advertise a 3,000-word piece as a one-minute read. The field is omitted rather
than guessed. Raising this number is an ingestion change, not a display one.

## Rights

See [DATA_RIGHTS.md](DATA_RIGHTS.md) and [PRIVACY.md](PRIVACY.md).

Publisher bodies, images and branding are not republished. A body-derived lead
sentence is used **only** for articles that are publicly readable; for paid or
locked articles the subtitle is the only text shown, and member previews are
never read at all.

### Planned sources

**SEC EDGAR** is rights-cleared in `config/source_rights.json` with status
`reviewed` and is not yet wired to an adapter. It is the next source to enable,
for company/ticker registry data behind ticker discovery.
