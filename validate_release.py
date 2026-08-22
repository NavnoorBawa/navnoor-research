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
        "your query stays in this page",
        "No quotes, holdings, scores, or investment recommendations",
    ):
        if exact not in html:
            problems.append(f"index.html is missing product contract text {exact!r}")
    if 'role="tab"' in html or 'role="tablist"' in html:
        problems.append("incomplete ARIA tab semantics returned to the navigation")
    if html.count("<h1") != 1 or "<h1 id=\"page-title\">Search</h1>" not in html:
        problems.append("index.html must contain one Search h1")
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
    except (OSError, ValueError) as exc:
        problems.append(f"release payload validation failed: {exc}")

    js_name = names.get("js", "")
    if js_name:
        script = (site / js_name).read_text(encoding="utf-8", errors="strict")
        for forbidden in (
            "localStorage", "sessionStorage", "pushState", "replaceState", "sendBeacon",
            "XMLHttpRequest", "WebSocket",
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
        ):
            if exact not in script:
                problems.append(f"client is missing linked GDELT attribution {exact!r}")

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
