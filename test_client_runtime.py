"""Execute the local-search contracts in the same JavaScript runtime shipped to readers."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import build_site

ROOT = Path(__file__).resolve().parent
APP = ROOT / "navnoor_research" / "assets" / "app.js"
RESEARCH_DATA = ROOT / "data" / "research.json"


FIXTURE = r"""
const assert = require("node:assert/strict");
const app = require(process.argv[1]);
const rid = (letter) => "r_" + letter.repeat(64);
const research = {
  research: [
    {access: "public", entities: ["rut"], id: rid("1"), published: "2026-08-20",
     source: "substack", title: "Russell small-cap field notes", topic: "equities",
     url: "https://navnoorbawa.substack.com/p/russell"},
    {access: "public", entities: ["machine-learning"], id: rid("2"), published: "2026-08-20",
     source: "medium", title: "Machine-learning research process", topic: "quant-methods",
     url: "https://medium.com/@navnoor/ai"},
    {access: "restricted", entities: ["sec"], id: rid("3"), published: "2026-08-20",
     source: "patreon", title: "SEC market-structure notes", topic: "regulation",
     url: "https://www.patreon.com/posts/sec"},
    {access: "public", entities: [], id: rid("4"), published: "2026-08-20",
     source: "substack", title: "NVIDIA Corporation research archive", topic: "equities",
     url: "https://navnoorbawa.substack.com/p/nvidia"}
  ]
};
const companies = {
  companies: [["0001045810", "NVDA", "Nasdaq", "NVIDIA CORP"]]
};
const news = {items: [], sources: {}};
const taxonomy = {
  entities: {
    rut: {aliases: ["RUT", "IWM", "Russell 2000"], kind: "index", label: "Russell 2000"},
    "machine-learning": {aliases: ["ML", "AI"], kind: "concept", label: "Machine learning"},
    sec: {aliases: ["SEC"], kind: "regulator", label: "U.S. Securities and Exchange Commission"}
  },
  topics: {equities: "Equities", "quant-methods": "Quant methods", regulation: "Regulation"},
  sources: {substack: "Substack", medium: "Medium", patreon: "Patreon"}
};
app.install([research, companies, news, taxonomy]);
app.state.topic = "";
app.state.access = "";
app.state.company = null;
app.state.sort = "newest";
"""


class TestClientRuntime(unittest.TestCase):
    def run_js(self, body: str) -> None:
        result = subprocess.run(
            ["node", "-e", FIXTURE + body, str(APP)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_reviewed_aliases_select_exact_entities(self):
        self.run_js(r"""
for (const [queryText, entityId, expectedId] of [
  ["IWM", "rut", rid("1")], ["AI", "machine-learning", rid("2")], ["SEC", "sec", rid("3")]
]) {
  app.state.query = queryText;
  app.state.company = null;
  const query = app.parseQuery();
  assert.equal(query.entityId, entityId);
  assert.deepEqual(app.selectRecords(app.data.research, query, "research").map((row) => row.id),
                   [expectedId]);
}
""")

    def test_bare_ticker_suggests_and_explicit_ticker_scopes(self):
        self.run_js(r"""
app.state.query = "NVDA";
let query = app.parseQuery();
assert.equal(query.company, null);
assert.equal(query.entityId, null);
assert.deepEqual(app.matchingCompanies(query).map((company) => company.ticker), ["NVDA"]);

app.state.query = "$NVDA";
query = app.parseQuery();
assert.equal(query.company.ticker, "NVDA");
assert.deepEqual(app.selectRecords(app.data.research, query, "research").map((row) => row.id),
                 [rid("4")]);
""")

    def test_equal_date_order_is_deterministic(self):
        self.run_js(r"""
app.state.query = "";
const query = app.parseQuery();
assert.deepEqual(app.selectRecords(app.data.research, query, "research").map((row) => row.id),
                 [rid("1"), rid("2"), rid("3"), rid("4")]);
""")

    def test_search_order_is_independent_from_hidden_dedicated_sort(self):
        self.run_js(r"""
app.state.sort = "oldest";
app.state.query = "";
app.data.research[0].published = "2026-08-21";
app.data.research[3].published = "2026-08-19";
let query = app.parseQuery();
let records = app.selectRecords(app.data.research, query, "research", "newest");
assert.deepEqual(records.map((row) => row.id), [rid("1"), rid("2"), rid("3"), rid("4")]);
assert.equal(app.state.sort, "oldest");

app.state.query = "machine learning";
query = app.parseQuery();
records = app.selectRecords(app.data.research, query, "research", "best");
assert.deepEqual(records.map((row) => row.id), [rid("2")]);
assert.equal(app.state.sort, "oldest");
""")

    def test_topic_selection_is_actionable_in_search_and_dedicated_views(self):
        self.run_js(r"""
app.state.view = "search";
app.state.query = "";
app.state.company = app.data.companies[0];
assert.equal(app.selectTopic("equities"), true);
assert.equal(app.state.query, "Equities");
assert.equal(app.state.company, null);
assert.equal(app.state.topic, "");

app.state.view = "research";
assert.equal(app.selectTopic("regulation"), true);
assert.equal(app.state.topic, "regulation");
assert.equal(app.selectTopic("not-reviewed"), false);
""")

    def test_gdelt_attribution_is_linked_without_weakening_other_sources(self):
        self.run_js(r"""
const linked = app.discoveryAttribution(
  "gdelt-doc-v2", "Discovery metadata: GDELT Project", "Discovery source: "
);
assert.match(linked, /Discovery source: <a href="https:\/\/www\.gdeltproject\.org\/"/);
assert.match(linked, /target="_blank" rel="noopener noreferrer"/);
assert.match(linked, />Discovery metadata: GDELT Project<\/a>$/);
assert.equal(
  app.discoveryAttribution("federal-reserve-rss", "Federal Reserve Board", "Source: "),
  "Source: Federal Reserve Board"
);
assert.equal(
  app.discoveryAttribution("gdelt-doc-v2", "<unsafe>", ""),
  '<a href="https://www.gdeltproject.org/" target="_blank" rel="noopener noreferrer">' +
    "&lt;unsafe&gt;</a>"
);
""")

    def test_company_action_has_a_specific_accessible_name(self):
        self.run_js(r"""
const html = app.companyRows(app.data.companies, 4);
assert.match(html, /<span class="ticker">NVDA<\/span>/);
assert.match(html, /<h4>NVIDIA CORP<\/h4>/);
assert.match(html,
  /aria-label="Search NVIDIA CORP">View matches <span aria-hidden="true">→<\/span><\/button>/);
assert.match(html, /aria-label="Open SEC record for NVIDIA CORP">SEC record<\/a>/);
const escaped = app.companyRows([{
  cik: "0000000001", ticker: "ACME", exchange: "NYSE",
  name: 'ACME & Co "A"', index: 7
}], 4);
assert.match(escaped, /<h4>ACME &amp; Co &quot;A&quot;<\/h4>/);
assert.match(escaped,
  /aria-label="Search ACME &amp; Co &quot;A&quot;">View matches/);
assert.match(escaped,
  /aria-label="Open SEC record for ACME &amp; Co &quot;A&quot;">SEC record<\/a>/);
""")

    def test_search_shortcut_requires_an_unmodified_non_editable_target(self):
        self.run_js(r"""
const target = {tagName: "DIV", isContentEditable: false};
const plain = {key: "/", altKey: false, ctrlKey: false, metaKey: false, shiftKey: false};
assert.equal(app.shouldFocusSearch(plain, target), true);
for (const modifier of ["altKey", "ctrlKey", "metaKey", "shiftKey"]) {
  const event = {...plain, [modifier]: true};
  assert.equal(app.shouldFocusSearch(event, target), false);
}
for (const editable of [
  {tagName: "INPUT", isContentEditable: false},
  {tagName: "TEXTAREA", isContentEditable: false},
  {tagName: "SELECT", isContentEditable: false},
  {tagName: "DIV", isContentEditable: true}
]) {
  assert.equal(app.shouldFocusSearch(plain, editable), false);
}
assert.equal(app.shouldFocusSearch({...plain, key: "?"}, target), false);
""")

    def test_source_health_exposes_machine_readable_check_times(self):
        self.run_js(r"""
app.data.newsStates = {
  "federal-reserve-rss": {
    attribution: "Federal Reserve Board", item_count: 3,
    label: "Federal Reserve Board", last_attempt_at: "2026-08-20T15:00:00Z",
    last_success_at: "2026-08-20T15:00:00Z", status: "ok"
  },
  "gdelt-doc-v2": {
    attribution: "Discovery metadata: GDELT Project", item_count: 0,
    label: "GDELT Project", last_attempt_at: "2026-08-20T16:00:00Z",
    last_success_at: null, status: "error"
  }
};
const html = app.renderSourceStates();
assert.match(html, /class="source-state__status">ok<\/span>/);
assert.match(html, /datetime="2026-08-20T15:00:00Z"/);
assert.match(html, /class="source-state__status">error<\/span>/);
assert.match(html, /datetime="2026-08-20T16:00:00Z"/);
assert.match(html, /last successful check not available/);
""")

    def test_search_group_pagination_is_explicit_and_resettable(self):
        self.run_js(r"""
assert.equal(
  app.searchMoreButton("companies", 8, 168),
  '<button type="button" class="more-button search-more" data-more-group="companies">' +
    "Show 8 more · 8 of 168 shown</button>"
);
assert.equal(app.searchMoreButton("research", 8, 8), "");
app.state.searchLimits.companies = 32;
app.state.searchLimits.research = 24;
app.state.searchLimits.news = 16;
app.resetSearchLimits();
assert.deepEqual(app.state.searchLimits, {companies: 8, research: 8, news: 8});
""")

    def test_payload_validators_reject_prohibited_or_impossible_metadata(self):
        self.run_js(r"""
const clone = (value) => JSON.parse(JSON.stringify(value));
const validResearch = {
  schema_version: 1, source_dataset_version: "a".repeat(64), source_revision: "b".repeat(40),
  research: [{access: "public", entities: ["rut"], id: rid("1"), published: "2026-08-20",
              source: "substack", title: "Russell small-cap field notes", topic: "equities",
              url: "https://navnoorbawa.substack.com/p/russell"}]
};
assert.equal(app.validateResearch(clone(validResearch)).research.length, 1);
for (const mutation of [
  (doc) => { delete doc.research[0].title; },
  (doc) => { doc.research[0].body_text = "not public metadata"; },
  (doc) => { doc.research[0].published = "2026-02-30"; }
]) {
  const document = clone(validResearch);
  mutation(document);
  assert.throws(() => app.validateResearch(document));
}

const validNews = {
  schema_version: 3,
  items: [{attribution: "Federal Reserve Board", entities: ["sec"], id: "n_" + "c".repeat(64),
           published: "2026-08-20T15:00:00Z", publisher: "www.federalreserve.gov",
           source_id: "federal-reserve-rss", title: "Federal Reserve issues statement",
           topic: "rates-macro", url: "https://www.federalreserve.gov/example"}],
  sources: {"federal-reserve-rss": {attribution: "Federal Reserve Board", item_count: 1,
            label: "Federal Reserve Board", last_attempt_at: "2026-08-20T15:00:00Z",
            last_success_at: "2026-08-20T15:00:00Z", status: "ok"}}
};
assert.equal(app.validateNews(clone(validNews)).items.length, 1);
for (const title of ["Market live updates", "Broker raises price target", "A buy recommendation",
                     "Bank upgraded Acme to Buy", "Goldman downgrades Acme",
                     "Analyst cuts Nvidia target to $100", "Wall Street says Nvidia is a buy",
                     "Top stock picks for 2026", "Acme upgraded after earnings"]) {
  const document = clone(validNews);
  document.items[0].title = title;
  assert.throws(() => app.validateNews(document));
}
const impossible = clone(validNews);
impossible.items[0].published = "2026-02-30T15:00:00Z";
assert.throws(() => app.validateNews(impossible));
""")

    def test_validator_accepts_the_exact_tracked_research_projection(self):
        script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const app = require(process.argv[1]);
const document = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
assert.equal(app.validateResearch(document).research.length, Number(process.argv[3]));
"""
        expected = json.loads(
            (ROOT / "seed" / "manifest.json").read_text(encoding="utf-8")
        )["counts"]["records"]
        result = subprocess.run(
            ["node", "-e", script, str(APP), str(RESEARCH_DATA), str(expected)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_validators_accept_every_exact_built_data_projection(self):
        script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const app = require(process.argv[1]);
const validators = ["validateResearch", "validateCompanies", "validateNews", "validateTaxonomy"];
for (let index = 0; index < validators.length; index += 1) {
  const document = JSON.parse(fs.readFileSync(process.argv[index + 2], "utf8"));
  assert.equal(app[validators[index]](document), document);
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            build_site.build_into(out, "d" * 40)
            app = next(out.glob("app-*.js"))
            payloads = [next(out.glob(f"{name}-*.json")) for name in (
                "research", "companies", "news", "taxonomy",
            )]
            result = subprocess.run(
                ["node", "-e", script, str(app), *(str(path) for path in payloads)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_bundle_has_no_query_persistence_or_navigation_channel(self):
        source = APP.read_text(encoding="utf-8")
        self.assertEqual(source.count("fetch("), 1)
        self.assertIn("var newsBody = renderSourceStates();", source)
        self.assertIn('data-more-group="', source)
        self.assertIn("revealed.length > previousSearchLimit", source)
        self.assertIn("revealedLinks.length > previousLimit", source)
        for channel in (
            "localStorage", "sessionStorage", "history.", "sendBeacon",
            "document.cookie", "indexedDB", "serviceWorker", "URLSearchParams",
            "window.location.search", "window.location.hash", "caches.",
        ):
            self.assertNotIn(channel, source)


if __name__ == "__main__":
    unittest.main()
