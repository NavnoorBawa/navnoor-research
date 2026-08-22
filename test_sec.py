"""SEC company registry: fixed request, strict projection, and safe promotion."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import refresh_companies
from navnoor_research import jsonio, paths
from navnoor_research.adapters import http, sec


def response(rows=None, fields=None, **extra):
    value = {
        "fields": list(sec.UPSTREAM_FIELDS) if fields is None else fields,
        "data": rows if rows is not None else [[1045810, "NVIDIA CORP", "NVDA", "Nasdaq"]],
    }
    value.update(extra)
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def one_company():
    return sec.parse_companies(response())[0]


class TestEndpointAndRequest(unittest.TestCase):
    def test_only_exact_reviewed_endpoint_is_accepted(self):
        sec.validate_endpoint(sec.ENDPOINT)
        for url in (
            "http://www.sec.gov/files/company_tickers_exchange.json",
            "https://data.sec.gov/files/company_tickers_exchange.json",
            "https://www.sec.gov/data/company_tickers_exchange.json",
            "https://www.sec.gov/files/company_tickers_exchange.json?x=1",
            "https://www.sec.gov/files/company_tickers_exchange.json#x",
            "https://www.sec.gov:443/files/company_tickers_exchange.json",
            "https://www.sec.gov.evil.example/files/company_tickers_exchange.json",
        ):
            with self.subTest(url=url), self.assertRaises(sec.SecError):
                sec.validate_endpoint(url)

    def test_collect_makes_one_bounded_request_without_retry(self):
        calls = []

        def fake_fetch(url, hosts, **kwargs):
            calls.append((url, tuple(hosts), kwargs))
            return response()

        companies = sec.collect(["www.sec.gov"], fetcher=fake_fetch)
        self.assertEqual(len(companies), 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], sec.ENDPOINT)
        self.assertEqual(calls[0][1], sec.ALLOWED_HOSTS)
        self.assertEqual(calls[0][2]["retries"], 0)
        self.assertEqual(calls[0][2]["max_bytes"], sec.MAX_RESPONSE_BYTES)
        self.assertEqual(calls[0][2]["timeout"], sec.TIMEOUT_SECONDS)
        self.assertEqual(calls[0][2]["accept"], "application/json")
        self.assertEqual(calls[0][2]["content_types"], ("application/json",))

    def test_collect_refuses_a_broader_or_different_host_list_before_fetch(self):
        calls = []

        def fake_fetch(*args, **kwargs):
            calls.append((args, kwargs))
            return response()

        for hosts in (["data.sec.gov"], ["www.sec.gov", "data.sec.gov"], []):
            with self.subTest(hosts=hosts), self.assertRaises(sec.SecError):
                sec.collect(hosts, fetcher=fake_fetch)
        self.assertEqual(calls, [])

    def test_shared_user_agent_identifies_product_and_contact(self):
        self.assertIn("navnoor research", http.USER_AGENT.lower())
        self.assertIn("@", http.USER_AGENT)


class TestResponseValidation(unittest.TestCase):
    def test_projected_company_has_full_identity_and_canonical_link(self):
        company = one_company()
        self.assertEqual(company.cik, "0001045810")
        self.assertEqual(company.ticker, "NVDA")
        self.assertEqual(len(company.id), 64)
        self.assertEqual(
            company.id,
            sec.company_id("0001045810", "NVDA", "Nasdaq"),
        )
        self.assertEqual(
            company.url,
            "https://www.sec.gov/edgar/browse/?CIK=0001045810",
        )
        self.assertEqual(set(company.to_json()), set(sec.PUBLIC_FIELDS))

    def test_nullable_exchange_is_preserved_as_an_explicit_empty_label(self):
        company = sec.parse_companies(response([[1109262, "Example Inc.", "AGGI", None]]))[0]
        self.assertEqual(company.exchange, "")

    def test_records_are_sorted_deterministically(self):
        rows = [
            [320193, "Apple Inc.", "AAPL", "Nasdaq"],
            [1045810, "NVIDIA CORP", "NVDA", "Nasdaq"],
        ]
        self.assertEqual(
            [item.ticker for item in sec.parse_companies(response(rows))],
            ["AAPL", "NVDA"],
        )

    def test_malformed_and_non_strict_json_are_refused(self):
        bad_payloads = (
            b"{not json",
            b'{' + b'"fields":[],"fields":[],"data":[]}',
            b'{"fields":[],"data":[],"n":NaN}',
            b'\xff',
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload), self.assertRaises(sec.SecError):
                sec.parse_companies(payload)

    def test_oversized_response_is_refused_before_parsing(self):
        with self.assertRaises(sec.SecError) as caught:
            sec.parse_companies(b"x" * (sec.MAX_RESPONSE_BYTES + 1))
        self.assertIn("byte ceiling", str(caught.exception))

    def test_top_level_and_field_declaration_must_be_exact(self):
        for payload in (
            response(extra="unexpected"),
            response(fields=["name", "cik", "ticker", "exchange"]),
            response(fields=list(sec.UPSTREAM_FIELDS) + ["filing_body"]),
        ):
            with self.subTest(payload=payload), self.assertRaises(sec.SecError):
                sec.parse_companies(payload)

    def test_record_count_is_bounded_before_rows_are_materialized(self):
        rows = [[1, "A", "A", "NYSE"]] * (sec.MAX_RECORDS + 1)
        with self.assertRaises(sec.SecError) as caught:
            sec.parse_companies(response(rows))
        self.assertIn("record ceiling", str(caught.exception))

    def test_duplicate_association_is_refused(self):
        row = [1045810, "NVIDIA CORP", "NVDA", "Nasdaq"]
        with self.assertRaises(sec.SecError) as caught:
            sec.parse_companies(response([row, row]))
        self.assertIn("duplicate", str(caught.exception))

    def test_each_field_is_type_shape_and_length_checked(self):
        bad_rows = (
            [True, "Name", "NAME", "NYSE"],
            [0, "Name", "NAME", "NYSE"],
            [10_000_000_000, "Name", "NAME", "NYSE"],
            [1, "", "NAME", "NYSE"],
            [1, " Name", "NAME", "NYSE"],
            [1, "Name\nInjected", "NAME", "NYSE"],
            [1, "N" * (sec.MAX_NAME_CHARS + 1), "NAME", "NYSE"],
            [1, "Name", "lower", "NYSE"],
            [1, "Name", "BAD TICKER", "NYSE"],
            [1, "Name", "T" * (sec.MAX_TICKER_CHARS + 1), "NYSE"],
            [1, "Name", "NAME", {"exchange": "NYSE"}],
            [1, "Name", "NAME", "N\nYSE"],
            [1, "Name", "NAME", "X" * (sec.MAX_EXCHANGE_CHARS + 1)],
            [1, "Name", "NAME"],
        )
        for row in bad_rows:
            with self.subTest(row=row), self.assertRaises(sec.SecError):
                sec.parse_companies(response([row]))

    def test_stored_record_recomputes_id_and_url_and_rejects_extra_fields(self):
        public = one_company().to_json()
        self.assertEqual(sec.validate_company(public).ticker, "NVDA")
        for key, value in (
            ("id", "0" * 64),
            ("url", "https://www.sec.gov/edgar/browse/?CIK=1"),
            ("cik", "1045810"),
        ):
            changed = dict(public)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(sec.SecError):
                sec.validate_company(changed)
        changed = dict(public, filing_body="forbidden")
        with self.assertRaises(sec.SecError):
            sec.validate_company(changed)
        changed = dict(public, exchange=None)
        with self.assertRaises(sec.SecError):
            sec.validate_company(changed)


class TestSnapshotAndPromotion(unittest.TestCase):
    CHECKED_AT = "2026-08-22T12:34:56Z"

    def test_snapshot_envelope_and_timestamp_are_exact(self):
        snapshot = refresh_companies.make_snapshot([one_company()], self.CHECKED_AT)
        self.assertEqual(set(snapshot), set(refresh_companies.SNAPSHOT_FIELDS))
        for invalid in (
            "2026-02-30T12:34:56Z",
            "2026-08-22T12:34:56+00:00",
            "2026-08-22T12:34Z",
        ):
            changed = dict(snapshot, checked_at=invalid)
            with self.subTest(invalid=invalid), self.assertRaises(
                refresh_companies.CompanyStoreError
            ):
                refresh_companies.validate_snapshot(changed)

    def test_promotion_is_atomic_and_invalid_update_keeps_previous_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "companies.json"
            with mock.patch.object(paths, "COMPANIES_PATH", target):
                refresh_companies.promote([one_company()], self.CHECKED_AT)
                before = target.read_bytes()
                with self.assertRaises(refresh_companies.CompanyStoreError):
                    refresh_companies.promote([], "2026-08-23T00:00:00Z")
                self.assertEqual(target.read_bytes(), before)

    def test_failed_refresh_retains_valid_last_known_good(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "companies.json"
            with mock.patch.object(paths, "COMPANIES_PATH", target):
                refresh_companies.promote([one_company()], self.CHECKED_AT)
                before = target.read_bytes()
                with mock.patch.object(sec, "collect", side_effect=http.FetchError("offline")):
                    self.assertEqual(refresh_companies.main([]), 1)
                self.assertEqual(target.read_bytes(), before)

    def test_corrupt_previous_snapshot_stops_before_network_or_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "companies.json"
            target.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            before = target.read_bytes()
            with mock.patch.object(paths, "COMPANIES_PATH", target):
                with mock.patch.object(sec, "collect") as collect:
                    self.assertEqual(refresh_companies.main([]), 1)
                    collect.assert_not_called()
                self.assertEqual(target.read_bytes(), before)

    def test_successful_refresh_writes_and_offline_mode_revalidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "companies.json"
            with mock.patch.object(paths, "COMPANIES_PATH", target):
                with mock.patch.object(sec, "collect", return_value=[one_company()]):
                    with mock.patch.object(
                        refresh_companies,
                        "utc_now_iso",
                        return_value=self.CHECKED_AT,
                    ):
                        self.assertEqual(refresh_companies.main([]), 0)
                self.assertEqual(refresh_companies.main(["--offline"]), 0)
                stored = refresh_companies.load_stored()
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored["source_id"], sec.SOURCE_ID)
            self.assertEqual(len(stored["items"]), 1)

    def test_snapshot_rejects_noncanonical_order_and_duplicate_items(self):
        companies = sec.parse_companies(
            response(
                [
                    [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                    [1045810, "NVIDIA CORP", "NVDA", "Nasdaq"],
                ]
            )
        )
        snapshot = refresh_companies.make_snapshot(companies, self.CHECKED_AT)
        reversed_snapshot = dict(snapshot, items=list(reversed(snapshot["items"])))
        with self.assertRaises(refresh_companies.CompanyStoreError):
            refresh_companies.validate_snapshot(reversed_snapshot)
        duplicate_snapshot = dict(snapshot, items=[snapshot["items"][0]] * 2)
        with self.assertRaises(refresh_companies.CompanyStoreError):
            refresh_companies.validate_snapshot(duplicate_snapshot)

    def test_rights_screen_matches_exact_public_projection(self):
        source = refresh_companies._reviewed_source()
        self.assertEqual(source.adapter, "sec")
        self.assertEqual(tuple(source.allowed_hosts), sec.ALLOWED_HOSTS)
        self.assertEqual(tuple(source.link_hosts), sec.ALLOWED_HOSTS)
        self.assertEqual(tuple(source.allowed_fields), sec.PUBLIC_FIELDS)
        self.assertEqual(source.status, "enabled")
        self.assertFalse(set(source.allowed_fields) & set(source.prohibited_fields))

    def test_strict_round_trip_has_no_unreviewed_keys(self):
        snapshot = refresh_companies.make_snapshot([one_company()], self.CHECKED_AT)
        encoded = jsonio.dumps_pretty(snapshot).encode("utf-8")
        decoded = refresh_companies.validate_snapshot(jsonio.loads_strict(encoded))
        self.assertEqual(set(decoded["items"][0]), set(sec.PUBLIC_FIELDS))


if __name__ == "__main__":
    unittest.main()
