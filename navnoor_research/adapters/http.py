"""The only outbound network path in this project.

Every request is bounded before it is made: HTTPS only, a reviewed host, a hard
timeout, a hard byte ceiling, and no redirect following. A redirect is treated
as an error rather than silently followed, because following one would leave the
reviewed host without the rights screen noticing.
"""

from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

USER_AGENT = "Navnoor Research/1.0 (Navnoor Bawa; navnoorbawa@gmail.com)"

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_BYTES = 4_000_000
DEFAULT_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5


class FetchError(Exception):
    """A bound was violated or the host could not be read."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise FetchError(f"redirect to {newurl!r} refused; reviewed host must answer directly")


def _verified_tls_context() -> ssl.SSLContext:
    """Use platform trust, with the standard macOS trust file as a secure fallback."""
    defaults = ssl.get_default_verify_paths()
    fallback = Path("/etc/ssl/cert.pem")
    if not defaults.cafile and not defaults.capath and fallback.is_file():
        return ssl.create_default_context(cafile=str(fallback))
    return ssl.create_default_context()


_TLS_CONTEXT = _verified_tls_context()
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=_TLS_CONTEXT),
    _NoRedirects(),
)


def check_url(url: str, allowed_hosts: Sequence[str]) -> str:
    """Validate scheme and host against the rights screen, returning the host."""
    if not isinstance(url, str) or not url or len(url) > 2_048:
        raise FetchError("URL must be a non-empty string of at most 2,048 characters")
    if any(ord(char) < 33 or ord(char) == 127 for char in url):
        raise FetchError("URL contains whitespace or a control character")
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as exc:
        raise FetchError(f"URL has an invalid port: {url!r}") from exc
    if (
        parts.scheme != "https" or not parts.hostname or parts.username or parts.password
        or parts.fragment or port not in (None, 443)
    ):
        raise FetchError(f"refusing non-HTTPS url {url!r}")
    host = (parts.hostname or "").lower()
    if host not in {h.lower() for h in allowed_hosts}:
        raise FetchError(f"host {host!r} is not in the reviewed allowlist {list(allowed_hosts)}")
    return host


def fetch(
    url: str,
    allowed_hosts: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retries: int = DEFAULT_RETRIES,
    accept: str | None = None,
    content_types: Sequence[str] = (),
    sleep=time.sleep,
) -> bytes:
    """Fetch a bounded body from a reviewed host, or raise FetchError."""
    check_url(url, allowed_hosts)

    request_headers = {"User-Agent": USER_AGENT}
    if accept:
        request_headers["Accept"] = accept
    request = urllib.request.Request(url, headers=request_headers, method="GET")

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                if response.status != 200:
                    raise FetchError(f"{url}: HTTP {response.status}")
                final_url = response.geturl() if hasattr(response, "geturl") else url
                if final_url != url:
                    raise FetchError(f"{url}: final response URL changed to {final_url!r}")
                response_headers = getattr(response, "headers", None)
                if content_types:
                    actual = (
                        response_headers.get_content_type().lower()
                        if response_headers is not None else ""
                    )
                    allowed_types = {value.lower() for value in content_types}
                    if actual not in allowed_types:
                        raise FetchError(
                            f"{url}: content type {actual or 'missing'!r} is not allowed"
                        )
                declared = (
                    response_headers.get("Content-Length")
                    if response_headers is not None else None
                )
                if declared is not None:
                    try:
                        declared_size = int(declared)
                    except ValueError as exc:
                        raise FetchError(f"{url}: invalid Content-Length") from exc
                    if declared_size < 0 or declared_size > max_bytes:
                        raise FetchError(f"{url}: declared body exceeds {max_bytes} byte ceiling")
                # Read one byte past the ceiling so an oversized body is
                # detected rather than silently truncated into the catalogue.
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise FetchError(f"{url}: response exceeds {max_bytes} byte ceiling")
                return body
        except FetchError:
            raise
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt < retries:
                sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise FetchError(f"{url}: unreachable after {retries + 1} attempts ({last})")
