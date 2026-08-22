#!/usr/bin/env python3
"""Verify a local or deployed release exactly as served over HTTP."""

from __future__ import annotations

import argparse
import http.server
import re
import socketserver
import sys
import threading
import urllib.error
import urllib.request
from functools import partial
from typing import Any
from urllib.parse import urljoin, urlsplit

from navnoor_research import jsonio, manifest, paths
from navnoor_research.fingerprint import sha256_hex

MAX_FILE_BYTES = 2_000_000
MAX_RELEASE_BYTES = 20_000


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: ANN001
        pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.URLError(f"redirect refused: {newurl}")


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _serve() -> tuple[socketserver.TCPServer, str]:
    handler = partial(_QuietHandler, directory=str(paths.DEFAULT_SITE_DIR))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def _base_url(value: str) -> str:
    text = value.rstrip("/") + "/"
    parts = urlsplit(text)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("smoke URL must not contain credentials, query, or fragment")
    if parts.scheme == "https" and parts.hostname:
        return text
    if parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}:
        return text
    raise ValueError("smoke URL must be HTTPS or loopback HTTP")


def _get(base: str, name: str, maximum: int) -> tuple[bytes, str]:
    url = urljoin(base, name)
    with OPENER.open(url, timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError(f"{name}: response was not exact HTTP 200")
        payload = response.read(maximum + 1)
        if len(payload) > maximum:
            raise ValueError(f"{name}: served body exceeds {maximum} bytes")
        return payload, response.headers.get_content_type().lower()


def check(base: str, expected_revision: str) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    try:
        release_bytes, release_type = _get(base, manifest.MANIFEST_NAME, MAX_RELEASE_BYTES)
        release = jsonio.loads_strict(release_bytes)
    except (OSError, ValueError, jsonio.JsonError, urllib.error.URLError) as exc:
        return {}, [f"release.json could not be read exactly: {exc}"]
    if release_type != "application/json":
        failures.append(f"release.json content type is {release_type!r}")
    structure = manifest.validate_document(release, expected_revision)
    if structure:
        envelope = release if isinstance(release, dict) else {}
        return envelope, failures + [f"served {problem}" for problem in structure]
    files = release["files"]

    served: dict[str, bytes] = {}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            failures.append("release contains an invalid file entry")
            continue
        name = entry["path"]
        maximum = MAX_FILE_BYTES
        try:
            payload, content_type = _get(base, name, maximum)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            failures.append(f"{name}: not served exactly ({exc})")
            continue
        served[name] = payload
        if len(payload) != entry.get("bytes") or sha256_hex(payload) != entry.get("sha256"):
            failures.append(f"{name}: served bytes do not match the release manifest")
        if name.endswith(".json") and content_type != "application/json":
            failures.append(f"{name}: JSON content type is {content_type!r}")
        if name.endswith(".js") and content_type not in {
            "application/javascript", "text/javascript",
        }:
            failures.append(f"{name}: JavaScript content type is {content_type!r}")
        if name.endswith(".css") and content_type != "text/css":
            failures.append(f"{name}: CSS content type is {content_type!r}")

    index = served.get("index.html", b"")
    if b"Content-Security-Policy" not in index:
        failures.append("served shell is missing its Content-Security-Policy")
    for label in (b">Search</button>", b">Research</button>", b">Market News</button>"):
        if label not in index:
            failures.append(f"served shell is missing {label!r}")
    references = {
        match.decode("utf-8")
        for match in re.findall(
            rb'(?:src|href|data-(?:research|companies|news|taxonomy))="([a-z0-9.-]+\.(?:css|js|json))"',
            index,
        )
    }
    if not references.issubset(served):
        failures.append("served shell references an asset outside the exact release")
    return release, failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--url", default="", help="deployed site root; omit for fixed local _site")
    args = parser.parse_args(argv)
    server = None
    try:
        if args.url:
            base = _base_url(args.url)
        else:
            if not paths.DEFAULT_SITE_DIR.is_dir():
                raise ValueError("fixed _site bundle is missing")
            server, base = _serve()
        release, failures = check(base, args.expected_revision)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    print(f"served    : {base}")
    print(f"revision  : {release.get('revision')}")
    print(f"files     : {release.get('file_count')}")
    for failure in failures:
        print(f"error     : {failure}", file=sys.stderr)
    if failures:
        print(f"\nFAILED with {len(failures)} problem(s)", file=sys.stderr)
        return 1
    print("\nexact HTTP smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
