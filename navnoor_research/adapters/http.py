"""The only outbound network path in this project.

Every request is bounded before it is made: HTTPS only, a reviewed host, a hard
timeout, a hard byte ceiling, and no redirect following. A redirect is treated
as an error rather than silently followed, because following one would leave the
reviewed host without the rights screen noticing.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from urllib.parse import urlsplit

USER_AGENT = "navnoor-research/2.0 (+https://github.com/NavnoorBawa; contact via repository)"

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_BYTES = 4_000_000
DEFAULT_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5


class FetchError(Exception):
    """A bound was violated or the host could not be read."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise FetchError(f"redirect to {newurl!r} refused; reviewed host must answer directly")


_OPENER = urllib.request.build_opener(_NoRedirects)


def check_url(url: str, allowed_hosts: Sequence[str]) -> str:
    """Validate scheme and host against the rights screen, returning the host."""
    parts = urlsplit(url)
    if parts.scheme != "https":
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
    sleep=time.sleep,
) -> bytes:
    """Fetch a bounded body from a reviewed host, or raise FetchError."""
    check_url(url, allowed_hosts)

    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers, method="GET")

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                if response.status != 200:
                    raise FetchError(f"{url}: HTTP {response.status}")
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
