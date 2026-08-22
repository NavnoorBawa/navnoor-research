"""End-to-end build, product-shell, determinism, and fixed-path release gates."""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import build_site
import validate_data
import validate_release
from navnoor_research import manifest, render

ROOT = Path(__file__).resolve().parent
REVISION = "a" * 40


class TestRender(unittest.TestCase):
    ASSETS = {
        "companies": "companies-2222222222222222.json",
        "css": "app-5555555555555555.css",
        "js": "app-6666666666666666.js",
        "news": "news-3333333333333333.json",
        "og": "og-7777777777777777.png",
        "research": "research-1111111111111111.json",
        "taxonomy": "taxonomy-4444444444444444.json",
    }

    def setUp(self):
        self.html = render.render(self.ASSETS, REVISION, 568, 10_403, 20, 2, 1)
        self.css = (ROOT / "navnoor_research" / "assets" / "app.css").read_text(
            encoding="utf-8"
        )
        self.js = (ROOT / "navnoor_research" / "assets" / "app.js").read_text(
            encoding="utf-8"
        )

    def test_public_information_architecture_is_exact(self):
        views = re.findall(
            r'class="view-button" data-view="([^"]+)"\s+aria-pressed="([^"]+)">([^<]+)</button>',
            self.html,
        )
        self.assertEqual(
            views,
            [
                ("search", "true", "Search"),
                ("research", "false", "Research"),
                ("news", "false", "Market News"),
            ],
        )
        self.assertNotIn('role="tab"', self.html)
        self.assertNotIn('role="tablist"', self.html)
        self.assertEqual(self.html.count("<h1"), 1)
        self.assertIn('<h1 id="page-title">Search</h1>', self.html)

    def test_search_name_is_stable_and_clear_is_outside_label(self):
        self.assertIn('<label class="search-label" for="query">Search</label>', self.html)
        self.assertIn('<button type="button" class="clear-button" id="clear"', self.html)
        label = re.search(r'<label class="search-label".*?</label>', self.html, re.DOTALL)
        self.assertIsNotNone(label)
        self.assertNotIn("Clear", label.group(0))
        self.assertNotIn("autofocus", self.html.lower())

    def test_privacy_and_product_limits_are_visible(self):
        self.assertIn("your query stays in this page", self.html)
        self.assertIn("never sent, stored, logged, or added to the URL", self.html)
        self.assertIn("No quotes, holdings, scores, or investment recommendations", self.html)

    def test_security_metadata_and_social_preview_are_complete(self):
        self.assertIn("default-src 'none'", self.html)
        self.assertIn("connect-src 'self'", self.html)
        self.assertNotIn("frame-ancestors", self.html)
        self.assertIn(render.PUBLIC_ORIGIN + self.ASSETS["og"], self.html)
        self.assertIn(f'<link rel="canonical" href="{render.PUBLIC_ORIGIN}">', self.html)

    def test_social_preview_is_a_bounded_landscape_asset(self):
        payload = (ROOT / "navnoor_research" / "assets" / "og.png").read_bytes()
        self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height = struct.unpack(">II", payload[16:24])
        self.assertGreaterEqual(width, 1_200)
        self.assertGreaterEqual(height, 630)
        self.assertGreaterEqual(width / height, 1.4)
        self.assertLessEqual(width / height, 2.0)
        self.assertLessEqual(len(payload), 1_500_000)

    def test_every_asset_name_is_escaped_and_present(self):
        for name in self.ASSETS.values():
            self.assertIn(name, self.html)
        tainted = dict(self.ASSETS, css='a"><script>x</script>')
        html = render.render(tainted, REVISION, 0, 0, 0, 0, 0)
        self.assertNotIn("<script>x</script>", html)

    def test_institutional_shell_keeps_status_and_skip_targets_accessible(self):
        for exact in (
            '<strong>NAVNOOR RESEARCH</strong>', 'Independent research archive',
            'Metadata &amp; provenance', 'class="index-bar"', 'class="market-strip"',
            'class="toolbar"',
            'class="footer"', '<main class="main" id="main" tabindex="-1">',
            'id="load-status" role="status" aria-live="polite" hidden',
            'aria-keyshortcuts="/" aria-describedby="search-privacy search-scope"',
            'Coverage: ticker, issuer, fund, regulator, and topic terms.',
            '<dt>Source coverage</dt><dd>\n        1 / 2 flagged</dd>',
        ):
            self.assertIn(exact, self.html)
        for theatrical in (
            "Public intelligence desk", "Content-addressed release",
            "Cross-source research intelligence", "Index mandate",
            "Supported syntax", "01 / Query", "Query handling", "Local to page",
        ):
            self.assertNotIn(theatrical, self.html)
        self.assertNotIn('class="terminal-id"', self.html)
        self.assertNotIn('class="coverage"', self.html)
        self.assertNotIn('class="edition"><i', self.html)
        self.assertNotIn('class="privacy-dot"', self.html)
        for value in (568, 10_403, 20):
            self.assertIn(f'<data value="{value}">', self.html)
        filters = re.search(r'<div class="filters".*?</div>', self.html, re.DOTALL)
        self.assertIsNotNone(filters)
        self.assertNotIn('id="result-count"', filters.group(0))
        self.assertEqual(self.html.count('id="result-count"'), 1)
        result_status = re.search(r'<span class="result-count"[^>]+>', self.html, re.DOTALL)
        self.assertIsNotNone(result_status)
        self.assertNotIn("hidden", result_status.group(0))
        self.assertIn('role="status"', result_status.group(0))
        self.assertIn('aria-live="polite"', result_status.group(0))
        self.assertIn('aria-atomic="true"', result_status.group(0))

    def test_institutional_styles_preserve_responsive_accessibility_modes(self):
        for exact in (
            '.intro__layout', 'body[data-view="search"] #results',
            '.group--research', '.group--news', '.source-state__status',
            'repeat(auto-fit, minmax(280px, 1fr))',
            '@media (max-width: 1240px)', '@media (max-width: 900px)',
            '@media (max-width: 720px)',
            '@media (max-width: 420px)',
            '@media (prefers-reduced-motion: reduce)',
            '@media (forced-colors: active)', '@media print',
            '.search-input:focus-visible',
        ):
            self.assertIn(exact, self.css)
        self.assertNotIn("@font-face", self.css)
        self.assertNotIn("https://", self.css)
        self.assertNotIn(".terminal-id", self.css)
        self.assertNotIn(".coverage", self.css)
        self.assertNotIn(".privacy-dot", self.css)
        self.assertIn("::selection { background: var(--accent); color: #ffffff; }", self.css)
        self.assertEqual(self.css.count("@media (forced-colors: active)"), 1)
        self.assertEqual(self.css.count("@media print"), 1)
        reduced = self.css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        self.assertIn("scroll-behavior: auto !important", reduced)
        self.assertIn("transition-duration: .01ms !important", reduced)
        forced = self.css.split("@media (forced-colors: active)", 1)[1]
        self.assertIn("outline: 3px solid Highlight", forced)
        self.assertIn("border: 2px solid CanvasText", forced)
        printed = self.css.split("@media print", 1)[1]
        self.assertIn("break-inside: avoid", printed)
        self.assertIn(".toolbar,", printed)
        self.assertIn(".index-bar,", printed)
        self.assertIn("color-scheme: light", printed)
        self.assertIn('body[data-view="search"] #results { display: block; }', printed)
        self.assertIn(".source-states { grid-template-columns: minmax(0, 1fr); }", self.css)
        self.assertIn(".company-meta a { text-decoration: underline", self.css)
        mobile = self.css.split("@media (max-width: 420px)", 1)[1]
        self.assertIn(
            ".index-bar__inner { display: grid; grid-template-columns: minmax(0, 1fr); }",
            mobile,
        )
        self.assertIn(".market-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }", mobile)
        self.assertIn("flex: 1 1 0", mobile)
        self.assertNotIn('class="dot publisher"', self.js)

        compact = self.css.split("@media (max-width: 1240px)", 1)[1].split(
            "@media (max-width: 900px)", 1
        )[0]
        self.assertRegex(
            compact,
            r"\.market-strip div\s*{[^}]*display:\s*grid;[^}]*gap:\s*5px;",
        )
        self.assertRegex(compact, r"\.market-strip dt\s*{[^}]*white-space:\s*normal;")
        self.assertRegex(compact, r"\.market-strip dd\s*{[^}]*white-space:\s*nowrap;")

        font_declarations = re.findall(r"(?:font-size|font):\s*([^;]+);", self.css)
        pixel_sizes = [
            float(match.group(1))
            for declaration in font_declarations
            if (match := re.search(r"(\d+(?:\.\d+)?)px", declaration))
        ]
        self.assertTrue(pixel_sizes)
        self.assertGreaterEqual(min(pixel_sizes), 11)

    def test_css_variables_are_defined_and_core_contrast_is_measurable(self):
        definitions = set(re.findall(r"--([a-z0-9-]+)\s*:", self.css))
        uses = set(re.findall(r"var\(--([a-z0-9-]+)\)", self.css))
        self.assertEqual(uses - definitions, set())

        root = re.search(r":root\s*{(.*?)}", self.css, re.DOTALL)
        self.assertIsNotNone(root)
        colors = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", root.group(1)))

        def luminance(value):
            channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [
                channel / 12.92 if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
                for channel in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(left, right):
            high, low = sorted((luminance(colors[left]), luminance(colors[right])), reverse=True)
            return (high + 0.05) / (low + 0.05)

        for background in ("bg", "surface", "surface-strong"):
            self.assertGreaterEqual(contrast("subtle", background), 4.5)
            self.assertGreaterEqual(contrast("line", background), 3.0)
            self.assertGreaterEqual(contrast("focus", background), 3.0)


class TestBuild(unittest.TestCase):
    def build(self, out: Path) -> dict:
        return build_site.build_into(out, REVISION)

    def test_build_is_byte_identical_across_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a"
            second = Path(tmp) / "b"
            release_a = self.build(first)
            release_b = self.build(second)
            self.assertEqual(release_a, release_b)
            for entry in release_a["files"]:
                self.assertEqual((first / entry["path"]).read_bytes(),
                                 (second / entry["path"]).read_bytes())

    def test_manifest_verifies_and_stale_files_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            (out / "stale-0000000000000000.js").write_text("old", encoding="utf-8")
            release = self.build(out)
            self.assertEqual(manifest.verify(out, release, REVISION), [])
            self.assertFalse((out / "stale-0000000000000000.js").exists())

    def test_browser_company_projection_is_compact_and_complete(self):
        research, companies, _ = validate_data.load_and_validate()
        public = build_site.public_companies(companies)
        self.assertEqual(public["fields"], ["cik", "ticker", "exchange", "name"])
        self.assertEqual(len(public["companies"]), len(companies["items"]))
        self.assertLess(len(json.dumps(public, separators=(",", ":")).encode()), 1_800_000)
        nvda = [row for row in public["companies"] if row[1] == "NVDA"]
        self.assertTrue(nvda)
        self.assertEqual(len(research["research"]), 568)

    def test_bundle_contains_no_prohibited_source_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            joined = b"\n".join(path.read_bytes() for path in out.glob("*.json"))
            for banned in (
                b'"body_text"', b'"member_preview"', b'"parser_observations"',
                b'"reading_minutes"', b'"recommendation"',
            ):
                self.assertNotIn(banned, joined)

    def test_bundle_has_exact_closed_set_and_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            release = self.build(out)
            names = {entry["path"] for entry in release["files"]}
            self.assertIn("index.html", names)
            self.assertIn(".nojekyll", names)
            self.assertEqual(len([name for name in names if name.endswith(".json")]), 4)
            self.assertEqual(len([name for name in names if name.startswith("og-")]), 1)
            self.assertLessEqual(release["total_bytes"], validate_release.TOTAL_BUDGET)
            interactive = sum(entry["bytes"] for entry in release["files"]
                              if not entry["path"].startswith("og-"))
            self.assertLessEqual(interactive, validate_release.INTERACTIVE_BUDGET)

    def test_social_card_bytes_are_bound_to_the_current_release_counts(self):
        payload = build_site.checked_social_card(build_site.SOCIAL_CARD_COUNTS)
        self.assertEqual(
            build_site.sha256_hex(payload),
            build_site.SOCIAL_CARD_SHA256,
        )
        for drifted in ((569, 10_403, 20), (568, 10_404, 20), (568, 10_403, 19)):
            with self.assertRaisesRegex(ValueError, "do not match"):
                build_site.checked_social_card(drifted)

    def test_cli_has_no_output_path_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "must-survive"
            sentinel.mkdir()
            result = subprocess.run(
                [sys.executable, "build_site.py", "--out", str(sentinel), "--revision", REVISION],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(sentinel.is_dir())
            self.assertEqual(list(sentinel.iterdir()), [])

    def test_legacy_output_environment_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "must-survive"
            sentinel.mkdir()
            env = dict(os.environ, SITE_OUTPUT_DIR=str(sentinel))
            result = subprocess.run(
                [sys.executable, "build_site.py", "--revision", "local-env-test"],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(sentinel.iterdir()), [])


class TestFixedReleaseGates(unittest.TestCase):
    def setUp(self):
        self.assertEqual(build_site.main(["--revision", "local-test"]), 0)

    def test_data_release_and_http_smoke_all_accept(self):
        self.assertEqual(validate_data.main([]), 0)
        result = subprocess.run(
            [sys.executable, "validate_release.py", "--expected-revision", "local-test"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            [sys.executable, "smoke_test_site.py", "--expected-revision", "local-test"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
