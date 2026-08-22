"""Strict projection of the SEC company/ticker association file.

The adapter has one reviewed request and no caller-supplied query.  It retains
only the four fields documented by the SEC, then adds a deterministic identity
and an SEC browse link.  It does not fetch filings or company submissions.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

from navnoor_research import jsonio
from navnoor_research.models import Company

from . import http

SOURCE_ID = "sec-edgar"
ENDPOINT = "https://www.sec.gov/files/company_tickers_exchange.json"
ALLOWED_HOSTS = ("www.sec.gov",)
UPSTREAM_FIELDS = ("cik", "name", "ticker", "exchange")
PUBLIC_FIELDS = ("id", "cik", "ticker", "exchange", "name", "url")

# The reviewed file is currently about 0.5 MB.  These ceilings leave room for
# growth while ensuring a changed endpoint cannot consume unbounded resources.
MAX_RESPONSE_BYTES = 2_000_000
MAX_RECORDS = 15_000
MAX_NAME_CHARS = 300
MAX_TICKER_CHARS = 20
MAX_EXCHANGE_CHARS = 40
TIMEOUT_SECONDS = 15.0

_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
_CIK = re.compile(r"^[0-9]{10}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SecError(ValueError):
    """The reviewed SEC response or a stored company record is invalid."""


def validate_endpoint(url: str) -> None:
    """Require the single reviewed SEC URL, including its exact path."""
    parts = urlsplit(url)
    if (
        url != ENDPOINT
        or parts.scheme != "https"
        or parts.netloc != ALLOWED_HOSTS[0]
        or parts.path != "/files/company_tickers_exchange.json"
        or parts.query
        or parts.fragment
        or parts.username is not None
        or parts.password is not None
        or parts.port is not None
    ):
        raise SecError(f"unreviewed SEC endpoint {url!r}")


def _text(value: Any, field: str, maximum: int, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise SecError(f"{field}: expected a string")
    if value != value.strip():
        raise SecError(f"{field}: leading or trailing whitespace is not permitted")
    if not value and not allow_empty:
        raise SecError(f"{field}: empty value")
    if len(value) > maximum:
        raise SecError(f"{field}: exceeds {maximum} character ceiling")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SecError(f"{field}: control character is not permitted")
    return value


def _cik(value: Any) -> str:
    if type(value) is not int or not 0 < value <= 9_999_999_999:
        raise SecError("cik: expected a positive integer of at most ten digits")
    return f"{value:010d}"


def _stored_cik(value: Any) -> str:
    cik = _text(value, "cik", 10)
    if not _CIK.fullmatch(cik) or int(cik) == 0:
        raise SecError("cik: expected a zero-padded ten-digit identifier")
    return cik


def _ticker(value: Any) -> str:
    ticker = _text(value, "ticker", MAX_TICKER_CHARS)
    if not _TICKER.fullmatch(ticker):
        raise SecError(f"ticker: unsupported value {ticker!r}")
    return ticker


def _exchange(value: Any) -> str:
    # SEC uses null when it knows a ticker association but has no exchange.
    if value is None:
        return ""
    return _text(value, "exchange", MAX_EXCHANGE_CHARS, allow_empty=True)


def _stored_exchange(value: Any) -> str:
    if type(value) is not str:
        raise SecError("exchange: expected a string")
    return _exchange(value)


def company_id(cik: str, ticker: str, exchange: str) -> str:
    """Return the full SHA-256 identity for one SEC association."""
    identity = "\0".join((SOURCE_ID, cik, ticker, exchange)).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


def company_url(cik: str) -> str:
    return f"https://www.sec.gov/edgar/browse/?CIK={cik}"


def _company(cik_value: Any, name_value: Any, ticker_value: Any, exchange_value: Any) -> Company:
    cik = _cik(cik_value)
    name = _text(name_value, "name", MAX_NAME_CHARS)
    ticker = _ticker(ticker_value)
    exchange = _exchange(exchange_value)
    return Company(
        id=company_id(cik, ticker, exchange),
        cik=cik,
        ticker=ticker,
        exchange=exchange,
        name=name,
        url=company_url(cik),
    )


def sort_key(company: Company) -> tuple[str, str, str, str]:
    return company.ticker, company.name, company.cik, company.exchange


def parse_companies(payload: bytes) -> list[Company]:
    """Validate and project the complete SEC response."""
    if type(payload) is not bytes:
        raise SecError("response must be bytes")
    if len(payload) > MAX_RESPONSE_BYTES:
        raise SecError(f"response exceeds {MAX_RESPONSE_BYTES} byte ceiling")
    try:
        raw = jsonio.loads_strict(payload)
    except jsonio.JsonError as exc:
        raise SecError(f"invalid SEC JSON: {exc}") from exc
    if type(raw) is not dict or set(raw) != {"fields", "data"}:
        raise SecError("response must contain exactly fields and data")
    if raw["fields"] != list(UPSTREAM_FIELDS):
        raise SecError(f"unexpected SEC field declaration {raw['fields']!r}")
    rows = raw["data"]
    if type(rows) is not list or not rows:
        raise SecError("data must be a non-empty array")
    if len(rows) > MAX_RECORDS:
        raise SecError(f"data exceeds {MAX_RECORDS} record ceiling")

    companies: list[Company] = []
    identities: set[str] = set()
    for index, row in enumerate(rows):
        if type(row) is not list or len(row) != len(UPSTREAM_FIELDS):
            raise SecError(f"data[{index}]: expected exactly four fields")
        try:
            company = _company(*row)
        except SecError as exc:
            raise SecError(f"data[{index}].{exc}") from exc
        if company.id in identities:
            raise SecError(f"data[{index}]: duplicate company association")
        identities.add(company.id)
        companies.append(company)
    return sorted(companies, key=sort_key)


def validate_company(value: Any) -> Company:
    """Validate one stored public record, including all derived fields."""
    if type(value) is not dict or set(value) != set(PUBLIC_FIELDS):
        raise SecError(f"stored company must contain exactly {list(PUBLIC_FIELDS)!r}")
    cik = _stored_cik(value["cik"])
    name = _text(value["name"], "name", MAX_NAME_CHARS)
    ticker = _ticker(value["ticker"])
    exchange = _stored_exchange(value["exchange"])
    identifier = _text(value["id"], "id", 64)
    if not _SHA256.fullmatch(identifier):
        raise SecError("id: expected a full lowercase SHA-256 digest")
    expected_id = company_id(cik, ticker, exchange)
    if identifier != expected_id:
        raise SecError("id: does not match the company association")
    url = _text(value["url"], "url", 100)
    if url != company_url(cik):
        raise SecError("url: does not match the canonical SEC browse URL")
    return Company(identifier, cik, ticker, exchange, name, url)


def collect(
    allowed_hosts: Sequence[str],
    *,
    fetcher: Callable[..., bytes] = http.fetch,
) -> list[Company]:
    """Make the one permitted SEC request and return validated companies."""
    validate_endpoint(ENDPOINT)
    if tuple(allowed_hosts) != ALLOWED_HOSTS:
        raise SecError(f"SEC host allowlist must be exactly {list(ALLOWED_HOSTS)!r}")
    payload = fetcher(
        ENDPOINT,
        allowed_hosts,
        timeout=TIMEOUT_SECONDS,
        max_bytes=MAX_RESPONSE_BYTES,
        retries=0,
        accept="application/json",
        content_types=("application/json",),
    )
    if type(payload) is not bytes:
        raise SecError("fetcher returned a non-bytes response")
    return parse_companies(payload)
