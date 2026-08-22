#!/usr/bin/env python3
"""Prove the fixed `_site` bundle is exact, complete, bounded, and source-safe."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any

import build_site
import validate_data
from navnoor_research import jsonio, manifest, paths
from navnoor_research.fingerprint import sha256_hex

TOTAL_BUDGET = 2_500_000
INTERACTIVE_BUDGET = 1_100_000
DATA_NAMES = ("research", "companies", "news", "taxonomy")
ASSET_NAMES = DATA_NAMES + ("css", "js")
PAYLOAD_RE = re.compile(r'data-(research|companies|news|taxonomy)="([^"]+)"')
CSS_RE = re.compile(r'<link rel="stylesheet" href="([^"]+)">')
JS_RE = re.compile(r'<script src="([^"]+)" defer></script>')
FINGERPRINT_RE = re.compile(r"^([a-z]+)-([0-9a-f]{16})\.(css|js|json|png)$")


def _luminance(value: str) -> float:
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(left: str, right: str) -> float:
    high, low = sorted((_luminance(left), _luminance(right)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _asset_names(html: str) -> dict[str, str]:
    names = dict(PAYLOAD_RE.findall(html))
    css = CSS_RE.findall(html)
    js = JS_RE.findall(html)
    if len(css) == 1:
        names["css"] = css[0]
    if len(js) == 1:
        names["js"] = js[0]
    og = re.findall(r'<meta property="og:image" content="([^"]+)">', html)
    if len(og) == 1:
        names["og"] = og[0].rsplit("/", 1)[-1]
    return names


def validate(expected_revision: str) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    site = paths.DEFAULT_SITE_DIR
    release_path = site / manifest.MANIFEST_NAME
    if not site.is_dir() or not release_path.is_file():
        return {}, ["fixed _site bundle or release.json is missing"]
    try:
        release = jsonio.load(release_path)
    except (OSError, jsonio.JsonError) as exc:
        return {}, [f"release manifest is invalid: {exc}"]
    problems.extend(manifest.verify(site, release, expected_revision))
    if release.get("total_bytes", TOTAL_BUDGET + 1) > TOTAL_BUDGET:
        problems.append(f"release exceeds the {TOTAL_BUDGET:,}-byte launch budget")
    interactive_bytes = sum(
        entry.get("bytes", 0) for entry in release.get("files", [])
        if isinstance(entry, dict) and not str(entry.get("path", "")).startswith("og-")
    )
    if interactive_bytes > INTERACTIVE_BUDGET:
        problems.append(f"interactive release exceeds the {INTERACTIVE_BUDGET:,}-byte budget")

    try:
        html = (site / "index.html").read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        return release, problems + [f"index.html is invalid UTF-8: {exc}"]
    for exact in (
        ">Search</button>", ">Research</button>", ">Market News</button>",
        'aria-label="Search controls"', '<label class="search-label" for="query">Search</label>',
        '<strong>NAVNOOR RESEARCH</strong>', 'Independent research archive',
        'Metadata &amp; provenance', 'class="index-bar"', 'class="market-strip"',
        'class="toolbar"', 'class="footer"',
        'aria-keyshortcuts="/" aria-describedby="search-privacy search-scope"',
        'aria-live="polite" aria-atomic="true"',
        'Coverage: ticker, issuer, fund, regulator, and topic terms.',
        '<dt>Source coverage</dt><dd>',
        "your query stays in this page",
        "No quotes, holdings, scores, or investment recommendations",
    ):
        if exact not in html:
            problems.append(f"index.html is missing product contract text {exact!r}")
    if 'role="tab"' in html or 'role="tablist"' in html:
        problems.append("incomplete ARIA tab semantics returned to the navigation")
    for theatrical in (
        "Public intelligence desk", "Content-addressed release",
        "Cross-source research intelligence", "Index mandate",
        "Supported syntax", "01 / Query", "Query handling", "Local to page",
    ):
        if theatrical in html:
            problems.append(f"faux-terminal interface copy returned: {theatrical!r}")
    if 'class="terminal-id"' in html or 'class="coverage"' in html:
        problems.append("faux-terminal interface chrome returned")
    if 'class="edition"><i' in html:
        problems.append("the masthead implies a live public-status signal")
    if 'class="privacy-dot"' in html:
        problems.append("the privacy disclosure must not mimic a live status signal")
    if html.count("<h1") != 1 or "<h1 id=\"page-title\">Search</h1>" not in html:
        problems.append("index.html must contain one Search h1")
    views = re.findall(
        r'class="view-button" data-view="([^"]+)"\s+aria-pressed="([^"]+)">([^<]+)</button>',
        html,
    )
    if views != [
        ("search", "true", "Search"),
        ("research", "false", "Research"),
        ("news", "false", "Market News"),
    ]:
        problems.append("the exact three-surface navigation contract changed")
    if "autofocus" in html.lower():
        problems.append("the page must not steal focus on load")
    if re.search(r'https?://[^"\s]+\.(?:js|css|woff2?)', html, re.IGNORECASE):
        problems.append("index.html references a remote executable or font")

    names = _asset_names(html)
    if set(names) != set(ASSET_NAMES) | {"og"}:
        problems.append("index.html asset references are incomplete or duplicated")
    for logical, name in names.items():
        match = FINGERPRINT_RE.fullmatch(name)
        expected_stem = "app" if logical in {"css", "js"} else logical
        if not match or match.group(1) != expected_stem:
            problems.append(f"{logical}: asset name is not its expected content address")
            continue
        path = site / name
        if not path.is_file():
            problems.append(f"{logical}: referenced asset is missing")
            continue
        if sha256_hex(path.read_bytes())[:16] != match.group(2):
            problems.append(f"{logical}: filename digest does not match exact bytes")

    try:
        research, companies, news = validate_data.load_and_validate()
        expected_docs = {
            "research": research,
            "companies": build_site.public_companies(companies),
            "news": news,
            "taxonomy": build_site.build_taxonomy(),
        }
        for logical in DATA_NAMES:
            name = names.get(logical, "")
            if name and jsonio.load(site / name) != expected_docs[logical]:
                problems.append(f"{logical}: public payload is not the exact validated projection")
        expected_counts = {
            "companies": len(companies["items"]),
            "entities": len(expected_docs["taxonomy"]["entities"]),
            "headlines": len(news["items"]),
            "research": len(research["research"]),
            "topics": len(expected_docs["taxonomy"]["topics"]),
        }
        if release.get("counts") != expected_counts:
            problems.append("release counts do not match exact payload records")
        metric_values = [int(value) for value in re.findall(r'<data value="(\d+)">', html)]
        if metric_values != [
            expected_counts["research"],
            expected_counts["companies"],
            expected_counts["headlines"],
        ]:
            problems.append("institutional index ledger counts are not the exact payload counts")
        social_counts = (
            expected_counts["research"],
            expected_counts["companies"],
            expected_counts["headlines"],
        )
        if social_counts != build_site.SOCIAL_CARD_COUNTS:
            problems.append("reviewed social-card facts do not match the release counts")
        source_issue_count = sum(
            source["status"] != "ok" for source in news["sources"].values()
        )
        expected_source_state = f"{source_issue_count} / {len(news['sources'])} flagged"
        if expected_source_state not in html:
            problems.append("archive ledger does not disclose the exact source issue count")
        og_name = names.get("og", "")
        if og_name and (site / og_name).is_file():
            if sha256_hex((site / og_name).read_bytes()) != build_site.SOCIAL_CARD_SHA256:
                problems.append("social card is not the reviewed count-bound asset")
    except (OSError, ValueError) as exc:
        problems.append(f"release payload validation failed: {exc}")

    js_name = names.get("js", "")
    if js_name:
        script = (site / js_name).read_text(encoding="utf-8", errors="strict")
        for forbidden in (
            "localStorage", "sessionStorage", "pushState", "replaceState", "sendBeacon",
            "XMLHttpRequest", "WebSocket", "document.cookie", "indexedDB", "serviceWorker",
            "URLSearchParams", "window.location.search", "window.location.hash", "caches.",
        ):
            if forbidden in script:
                problems.append(f"client privacy boundary contains {forbidden}")
        if script.count("fetch(") != 1 or "credentials: \"omit\"" not in script:
            problems.append("client network boundary is not the single same-origin loader")
        for exact in (
            "https://www.gdeltproject.org/",
            "discoveryAttribution(id, source.label",
            "discoveryAttribution(\n        record.source_id, record.attribution",
            'rel="noopener noreferrer"',
            "document.body.dataset.view = state.view",
            'aria-label="Search ',
            'aria-label="Open SEC record for ',
            'class="source-state__status"',
            '<time datetime="',
            "shouldFocusSearch(event, target)",
            "var newsBody = renderSourceStates();",
            'data-more-group="',
            "revealed.length > previousSearchLimit",
            "revealedLinks.length > previousLimit",
        ):
            if exact not in script:
                problems.append(f"client UI contract is missing {exact!r}")

    css_name = names.get("css", "")
    if css_name:
        style = (site / css_name).read_text(encoding="utf-8", errors="strict")
        for exact in (
            '.intro__layout', 'body[data-view="search"] #results',
            '.group--research', '.group--news', '.source-state__status',
            'repeat(auto-fit, minmax(280px, 1fr))',
            '@media (max-width: 1240px)', '@media (max-width: 900px)',
            '@media (max-width: 720px)',
            '@media (max-width: 420px)', '@media (prefers-reduced-motion: reduce)',
            '@media (forced-colors: active)', '@media print', 'color-scheme: light',
            '.index-bar__inner { display: grid; grid-template-columns: minmax(0, 1fr); }',
            '.market-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }',
        ):
            if exact not in style:
                problems.append(f"institutional responsive style contract is missing {exact!r}")
        if ".terminal-id" in style or ".coverage" in style:
            problems.append("obsolete terminal or mandate styles returned")
        if ".privacy-dot" in style:
            problems.append("privacy disclosure styling mimics a live status signal")
        if "::selection { background: var(--accent); color: #ffffff; }" not in style:
            problems.append("custom selection colors do not preserve readable contrast")
        compact_parts = style.split("@media (max-width: 1240px)", 1)
        compact_style = (
            compact_parts[1].split("@media (max-width: 900px)", 1)[0]
            if len(compact_parts) == 2 else ""
        )
        for pattern in (
            r"\.market-strip div\s*{[^}]*display:\s*grid;[^}]*gap:\s*5px;",
            r"\.market-strip dt\s*{[^}]*white-space:\s*normal;",
            r"\.market-strip dd\s*{[^}]*white-space:\s*nowrap;",
        ):
            if not re.search(pattern, compact_style):
                problems.append("responsive archive ledger does not prevent label/value collisions")
                break
        font_declarations = re.findall(r"(?:font-size|font):\s*([^;]+);", style)
        pixel_sizes = [
            float(match.group(1))
            for declaration in font_declarations
            if (match := re.search(r"(\d+(?:\.\d+)?)px", declaration))
        ]
        if not pixel_sizes or min(pixel_sizes) < 11:
            problems.append("CSS contains public interface type below the 11px floor")
        definitions = set(re.findall(r"--([a-z0-9-]+)\s*:", style))
        uses = set(re.findall(r"var\(--([a-z0-9-]+)\)", style))
        if uses - definitions:
            problems.append(f"CSS uses undefined variables: {sorted(uses - definitions)!r}")
        root = re.search(r":root\s*{(.*?)}", style, re.DOTALL)
        colors = dict(re.findall(
            r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});",
            root.group(1) if root else "",
        ))
        for foreground, minimum in (("subtle", 4.5), ("line", 3.0), ("focus", 3.0)):
            for background in ("bg", "surface", "surface-strong"):
                if foreground not in colors or background not in colors:
                    problems.append(f"CSS contrast token {foreground}/{background} is missing")
                elif _contrast(colors[foreground], colors[background]) < minimum:
                    problems.append(
                        f"CSS contrast token {foreground}/{background} is below {minimum:.1f}:1"
                    )

    listed = {entry.get("path") for entry in release.get("files", []) if isinstance(entry, dict)}
    expected_files = {".nojekyll", "index.html", *names.values()}
    if listed != expected_files:
        problems.append("release manifest file set is not the exact public closed set")
    return release, problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args(argv)
    release, problems = validate(args.expected_revision)
    print(f"site      : {paths.DEFAULT_SITE_DIR}")
    print(f"revision  : {release.get('revision')}")
    print(f"files     : {release.get('file_count')}")
    print(f"bytes     : {release.get('total_bytes', 0):,}")
    for problem in problems:
        print(f"error     : {problem}", file=sys.stderr)
    if problems:
        print(f"\nFAILED with {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("\nexact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
