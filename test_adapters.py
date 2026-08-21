"""Adapter bounds: hosts, schemes, redirects, byte ceilings, XXE, field allowlists."""

from __future__ import annotations

import unittest

from navnoor_research.adapters import gdelt, http, rss

HOSTS = ["www.federalreserve.gov"]


class TestUrlGuards(unittest.TestCase):
    def test_https_required(self):
        with self.assertRaises(http.FetchError):
            http.check_url("http://www.federalreserve.gov/x", HOSTS)

    def test_host_must_be_reviewed(self):
        with self.assertRaises(http.FetchError):
            http.check_url("https://evil.example/x", HOSTS)

    def test_lookalike_host_is_refused(self):
        with self.assertRaises(http.FetchError):
            http.check_url("https://www.federalreserve.gov.evil.example/x", HOSTS)

    def test_reviewed_host_passes(self):
        self.assertEqual(http.check_url("https://www.federalreserve.gov/a", HOSTS),
                         "www.federalreserve.gov")


class TestFetchBounds(unittest.TestCase):
    def test_oversized_body_is_refused(self):
        class _Response:
            status = 200
            def read(self, n): return b"x" * n
            def __enter__(self): return self
            def __exit__(self, *a): return False

        original = http._OPENER.open
        http._OPENER.open = lambda *a, **k: _Response()
        try:
            with self.assertRaises(http.FetchError) as ctx:
                http.fetch("https://www.federalreserve.gov/x", HOSTS, max_bytes=10)
            self.assertIn("ceiling", str(ctx.exception))
        finally:
            http._OPENER.open = original

    def test_redirect_handler_refuses(self):
        handler = http._NoRedirects()
        with self.assertRaises(http.FetchError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/")


class TestRssSafety(unittest.TestCase):
    XXE = (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           b"<rss><channel><item><title>&x;</title></item></channel></rss>")

    FEED = b"""<?xml version="1.0"?><rss><channel>
      <item>
        <title>Federal Reserve issues FOMC statement</title>
        <link>https://www.federalreserve.gov/a.htm</link>
        <pubDate>Wed, 20 Aug 2026 14:00:00 GMT</pubDate>
        <description>A description.</description>
        <category>Monetary Policy</category>
      </item>
      <item>
        <title>Insecure link</title>
        <link>http://www.federalreserve.gov/b.htm</link>
        <pubDate>Wed, 20 Aug 2026 14:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    def test_dtd_is_refused(self):
        with self.assertRaises(rss.FeedError):
            rss.parse_xml(self.XXE)

    def test_malformed_xml_is_refused(self):
        with self.assertRaises(rss.FeedError):
            rss.parse_xml(b"<rss><channel>")

    def test_items_are_projected_onto_allowed_fields(self):
        items = rss.parse_items(self.FEED)
        self.assertEqual(len(items), 1, "the non-HTTPS item must be dropped")
        item = items[0]
        self.assertEqual(item["published_at"], "2026-08-20T14:00:00Z")
        self.assertEqual(item["category"], "Monetary Policy")
        self.assertTrue(set(item).issubset(rss.ALLOWED_FIELDS))

    def test_collect_rejects_unknown_source(self):
        with self.assertRaises(rss.FeedError):
            rss.collect("not-a-source", HOSTS)


class TestGdeltProjection(unittest.TestCase):
    PAYLOAD = (b'{"articles":[{"url":"https://example.com/a","title":"Oil steadies",'
               b'"domain":"example.com","seendate":"20260821T083000Z","language":"English",'
               b'"sourcecountry":"United States","socialimage":"https://x/y.jpg","tone":-2.5},'
               b'{"url":"https://example.com/b","title":"Ignorado","language":"Spanish"}]}')

    def test_prohibited_fields_are_dropped(self):
        records = gdelt.parse_articles(self.PAYLOAD)
        self.assertEqual(len(records), 1, "non-English record must be dropped")
        self.assertTrue(set(records[0]).issubset(gdelt.ALLOWED_FIELDS))
        self.assertNotIn("socialimage", records[0])
        self.assertNotIn("tone", records[0])

    def test_seen_at_is_widened(self):
        self.assertEqual(gdelt._seen_at("20260821T083000Z"), "2026-08-21T08:30:00Z")

    def test_malformed_json_is_refused(self):
        with self.assertRaises(gdelt.GdeltError):
            gdelt.parse_articles(b"{not json")

    def test_query_carries_no_user_input(self):
        # Every query the adapter can issue is one of the reviewed constants.
        for key, query in gdelt.REVIEWED_QUERIES.items():
            self.assertIn(query, gdelt.query_url(query).replace("%22", '"')
                          .replace("+", " ").replace("%28", "(").replace("%29", ")"))

    def test_one_failing_query_does_not_lose_the_others(self):
        calls = {"n": 0}

        def flaky(url, hosts, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise http.FetchError("boom")
            return self.PAYLOAD

        records = gdelt.collect(["api.gdeltproject.org"],
                                queries=["markets", "rates"], fetcher=flaky)
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
