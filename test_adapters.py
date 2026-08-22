"""Network and headline-adapter bounds, projections, and failure isolation."""

from __future__ import annotations

import json
import unittest
import urllib.request
from email.message import Message
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from navnoor_research.adapters import gdelt, http, rss

FED_HOSTS = ["www.federalreserve.gov"]
GDELT_HOSTS = ["api.gdeltproject.org"]


class Response:
    def __init__(
        self,
        body=b"ok",
        *,
        status=200,
        url="https://www.federalreserve.gov/feed.xml",
        content_type="application/json",
        content_length=None,
    ):
        self.body = body
        self.status = status
        self.url = url
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, size):
        return self.body[:size]

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestUrlAndTransportGuards(unittest.TestCase):
    URL = "https://www.federalreserve.gov/feed.xml"

    def test_only_credential_free_https_on_a_reviewed_host_is_accepted(self):
        self.assertEqual(http.check_url(self.URL, FED_HOSTS), FED_HOSTS[0])
        invalid = (
            "http://www.federalreserve.gov/feed.xml",
            "https://evil.example/feed.xml",
            "https://www.federalreserve.gov.evil.example/feed.xml",
            "https://user@www.federalreserve.gov/feed.xml",
            "https://www.federalreserve.gov:444/feed.xml",
            "https://www.federalreserve.gov/feed.xml#fragment",
            "https://www.federalreserve.gov/feed.xml\n",
            "",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(http.FetchError):
                http.check_url(url, FED_HOSTS)

    def test_global_opener_has_no_environment_proxy_handler(self):
        handlers = [
            handler for handler in http._OPENER.handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        ]
        self.assertTrue(all(not handler.proxies for handler in handlers))

    def test_redirect_handler_refuses_even_same_host_redirects(self):
        handler = http._NoRedirects()
        with self.assertRaises(http.FetchError):
            handler.redirect_request(
                None, None, 302, "Found", {},
                "https://www.federalreserve.gov/moved.xml",
            )

    def test_changed_final_response_url_is_refused(self):
        response = Response(url="https://www.federalreserve.gov/moved.xml")
        with mock.patch.object(http._OPENER, "open", return_value=response):
            with self.assertRaises(http.FetchError) as caught:
                http.fetch(self.URL, FED_HOSTS, retries=0)
        self.assertIn("final response URL changed", str(caught.exception))

    def test_content_type_is_checked_without_sniffing(self):
        for content_type in ("text/html", None):
            response = Response(content_type=content_type)
            with self.subTest(content_type=content_type):
                with mock.patch.object(http._OPENER, "open", return_value=response):
                    with self.assertRaises(http.FetchError):
                        http.fetch(
                            self.URL, FED_HOSTS, retries=0,
                            content_types=("application/json",),
                        )

        response = Response(content_type="application/json; charset=utf-8")
        with mock.patch.object(http._OPENER, "open", return_value=response):
            self.assertEqual(
                http.fetch(
                    self.URL, FED_HOSTS, retries=0,
                    content_types=("application/json",),
                ),
                b"ok",
            )

    def test_declared_and_streamed_byte_ceilings_are_enforced(self):
        declared = Response(body=b"short", content_length=11)
        with mock.patch.object(http._OPENER, "open", return_value=declared):
            with self.assertRaises(http.FetchError) as caught:
                http.fetch(self.URL, FED_HOSTS, max_bytes=10, retries=0)
        self.assertIn("declared body", str(caught.exception))

        streamed = Response(body=b"x" * 11)
        with mock.patch.object(http._OPENER, "open", return_value=streamed):
            with self.assertRaises(http.FetchError) as caught:
                http.fetch(self.URL, FED_HOSTS, max_bytes=10, retries=0)
        self.assertIn("response exceeds", str(caught.exception))

    def test_invalid_content_length_is_refused(self):
        for value in ("not-a-number", -1):
            response = Response(content_length=value)
            with self.subTest(value=value):
                with mock.patch.object(http._OPENER, "open", return_value=response):
                    with self.assertRaises(http.FetchError):
                        http.fetch(self.URL, FED_HOSTS, retries=0)

    def test_accept_header_and_timeout_reach_the_single_request(self):
        response = Response()
        with mock.patch.object(http._OPENER, "open", return_value=response) as opened:
            http.fetch(
                self.URL, FED_HOSTS, timeout=7.0, retries=0,
                accept="application/json",
            )
        request = opened.call_args.args[0]
        self.assertEqual(opened.call_args.kwargs["timeout"], 7.0)
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_method(), "GET")


class TestRssSafety(unittest.TestCase):
    VALID_ITEM = """
      <item>
        <guid>fed-1</guid>
        <title>Federal Reserve issues FOMC statement</title>
        <link>https://www.federalreserve.gov/a.htm</link>
        <pubDate>Wed, 20 Aug 2026 14:00:00 GMT</pubDate>
        <description>A checked description.</description>
        <category>Monetary Policy</category>
      </item>
    """

    @staticmethod
    def feed(items):
        document = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<rss><channel>{items}</channel></rss>"
        )
        return document.encode()

    def test_utf16_encoded_xxe_is_refused_before_xml_parsing(self):
        dangerous = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            '<rss><channel><item><title>&x;</title></item></channel></rss>'
        ).encode("utf-16")
        with self.assertRaises(rss.FeedError):
            rss.parse_xml(dangerous)

    def test_utf8_dtd_and_declared_non_utf8_are_refused(self):
        payloads = (
            b'<?xml version="1.0"?><!DOCTYPE r><rss/>',
            b'<?xml version="1.0" encoding="ISO-8859-1"?><rss/>',
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(rss.FeedError):
                rss.parse_xml(payload)

    def test_malformed_xml_is_refused(self):
        with self.assertRaises(rss.FeedError):
            rss.parse_xml(b"<rss><channel>")

    def test_projection_contains_only_reviewed_fields(self):
        items = rss.parse_items(self.feed(self.VALID_ITEM), FED_HOSTS)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published_at"], "2026-08-20T14:00:00Z")
        self.assertEqual(items[0]["category"], "Monetary Policy")
        self.assertEqual(items[0]["guid"], "fed-1")
        self.assertTrue(set(items[0]).issubset(rss.ALLOWED_FIELDS))

    def test_off_host_item_link_fails_the_feed_closed(self):
        item = self.VALID_ITEM.replace(
            "https://www.federalreserve.gov/a.htm",
            "https://evil.example/a.htm",
        )
        with self.assertRaises(rss.FeedError) as caught:
            rss.parse_items(self.feed(item), FED_HOSTS)
        self.assertIn("outside reviewed hosts", str(caught.exception))

    def test_item_count_is_bounded(self):
        item = (
            "<item><title>Statement</title>"
            "<link>https://www.federalreserve.gov/a.htm</link></item>"
        )
        payload = self.feed(item * (rss.MAX_ITEMS_PER_FEED + 1))
        with self.assertRaises(rss.FeedError) as caught:
            rss.parse_items(payload, FED_HOSTS)
        self.assertIn("item ceiling", str(caught.exception))

    def test_title_summary_and_category_limits_are_enforced(self):
        fields = (
            ("title", rss.MAX_TITLE_CHARS + 1),
            ("description", rss.MAX_SUMMARY_CHARS + 1),
            ("category", 121),
        )
        for tag, length in fields:
            item = (
                "<item><title>Title</title>"
                "<link>https://www.federalreserve.gov/a.htm</link>"
                f"<{tag}>{'x' * length}</{tag}></item>"
            )
            if tag == "title":
                item = (
                    f"<item><title>{'x' * length}</title>"
                    "<link>https://www.federalreserve.gov/a.htm</link></item>"
                )
            with self.subTest(tag=tag), self.assertRaises(rss.FeedError):
                rss.parse_items(self.feed(item), FED_HOSTS)

    def test_guid_is_bounded_when_the_feed_uses_it_as_identity_metadata(self):
        item = self.VALID_ITEM.replace("fed-1", "g" * 3_000)
        projected = rss.parse_items(self.feed(item), FED_HOSTS)[0]
        self.assertEqual(len(projected["guid"]), 2_048)

    def test_collect_uses_bounded_content_typed_fetch_and_link_allowlist(self):
        calls = []

        def fake_fetch(url, hosts, **kwargs):
            calls.append((url, hosts, kwargs))
            return self.feed(self.VALID_ITEM)

        items = rss.collect(
            "federal-reserve-rss", FED_HOSTS, FED_HOSTS, fetcher=fake_fetch
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2]["max_bytes"], rss.MAX_FEED_BYTES)
        self.assertIn("application/xml", calls[0][2]["content_types"])

    def test_collect_rejects_unknown_source_without_fetching(self):
        fetcher = mock.Mock()
        with self.assertRaises(rss.FeedError):
            rss.collect("not-reviewed", FED_HOSTS, FED_HOSTS, fetcher=fetcher)
        fetcher.assert_not_called()


class TestGdeltProjection(unittest.TestCase):
    @staticmethod
    def payload(articles):
        return json.dumps({"articles": articles}, separators=(",", ":")).encode()

    @staticmethod
    def row(**overrides):
        value = {
            "url": "https://News.Example.com/markets/a",
            "title": "Oil steadies after policy decision",
            "domain": "untrusted-upstream-label.example",
            "seendate": "20260821T083000Z",
            "language": "English",
            "sourcecountry": "United States",
            "socialimage": "https://images.example/a.jpg",
            "tone": -2.5,
            "snippet": "publisher body excerpt",
        }
        value.update(overrides)
        return value

    def test_projection_drops_prohibited_fields_and_canonicalises_publisher(self):
        records = gdelt.parse_articles(self.payload([self.row()]))
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["domain"], "news.example.com")
        self.assertEqual(record["seen_at"], "2026-08-21T08:30:00Z")
        self.assertTrue(set(record).issubset(gdelt.ALLOWED_FIELDS))
        for prohibited in ("socialimage", "tone", "snippet"):
            self.assertNotIn(prohibited, record)

    def test_non_english_and_invalid_seen_dates_are_dropped(self):
        rows = [
            self.row(language="Spanish"),
            self.row(seendate="20260230T083000Z"),
        ]
        self.assertEqual(gdelt.parse_articles(self.payload(rows)), [])

    def test_strict_json_and_entry_shapes_are_enforced(self):
        payloads = (
            b"{not json",
            b'{"articles":[],"articles":[]}',
            b'{"articles":[],"n":NaN}',
            b'{"articles":{}}',
            b'{"articles":[1]}',
            b"\xff",
            self.payload([self.row(title=7)]),
            self.payload([self.row(url={"unexpected": "shape"})]),
            self.payload([self.row(seendate=False)]),
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(gdelt.GdeltError):
                gdelt.parse_articles(payload)

    def test_record_and_title_ceilings_are_enforced(self):
        too_many = [self.row(url=f"https://example.com/{index}")
                    for index in range(gdelt.MAX_RECORDS + 1)]
        with self.assertRaises(gdelt.GdeltError):
            gdelt.parse_articles(self.payload(too_many))
        with self.assertRaises(gdelt.GdeltError):
            gdelt.parse_articles(
                self.payload([self.row(title="x" * (gdelt.MAX_TITLE_CHARS + 1))])
            )

    def test_publisher_url_must_be_canonical_https(self):
        invalid = (
            "http://example.com/a",
            "https://user@example.com/a",
            "https://example.com:444/a",
            "https://example.com/a#fragment",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(gdelt.GdeltError):
                gdelt.parse_articles(self.payload([self.row(url=url)]))

    def test_query_shape_is_fixed_and_contains_no_reader_input(self):
        for query in gdelt.REVIEWED_QUERIES.values():
            parsed = urlsplit(gdelt.query_url(query))
            params = parse_qs(parsed.query)
            self.assertEqual(f"{query} sourcelang:english", params["query"][0])
            self.assertEqual(str(gdelt.MAX_RECORDS), params["maxrecords"][0])
            self.assertEqual(gdelt.TIMESPAN, params["timespan"][0])

    def test_one_query_failure_returns_partial_evidence_and_keeps_success(self):
        calls = []

        def flaky(url, hosts, **kwargs):
            calls.append((url, hosts, kwargs))
            if len(calls) == 1:
                raise http.FetchError("first query unavailable")
            return self.payload([self.row()])

        reviewed = {"first": "first fixed query", "second": "second fixed query"}
        with mock.patch.dict(gdelt.REVIEWED_QUERIES, reviewed, clear=True):
            records, errors = gdelt.collect(
                GDELT_HOSTS, queries=("first", "second"), fetcher=flaky
            )
        self.assertEqual(len(records), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("first", errors[0])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[2]["retries"] == 0 for call in calls))

    def test_all_queries_failing_raises_instead_of_claiming_empty_success(self):
        with self.assertRaises(gdelt.GdeltError):
            gdelt.collect(
                GDELT_HOSTS,
                fetcher=mock.Mock(side_effect=http.FetchError("offline")),
            )

    def test_unreviewed_query_key_is_rejected_before_fetch(self):
        fetcher = mock.Mock()
        with self.assertRaises(gdelt.GdeltError):
            gdelt.collect(GDELT_HOSTS, queries=("reader-input",), fetcher=fetcher)
        fetcher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
