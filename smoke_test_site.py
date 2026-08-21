#!/usr/bin/env python3
"""Serve a built bundle and verify it over HTTP the way a reader would get it.

    python3 smoke_test_site.py --site _site

Starts a local server on an ephemeral port, requests every file the manifest
lists, and checks the shell's guarantees: a content security policy is present,
every referenced asset resolves, and no off-origin host is requested.
"""

from __future__ import annotations

import argparse
import http.server
import json
import re
import socketserver
import sys
import threading
import urllib.request
from functools import partial
from pathlib import Path

from navnoor_research import manifest
from navnoor_research.fingerprint import sha256_hex

# Any absolute URL in the shell or its assets would be an off-origin request.
OFFSITE_RE = re.compile(rb"""(?:src|href)\s*=\s*["'](https?:)?//""", re.IGNORECASE)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: ANN001
        pass


def serve(site_dir: Path):
    handler = partial(_QuietHandler, directory=str(site_dir))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]


def get(base: str, path: str) -> bytes:
    with urllib.request.urlopen(f"{base}/{path}", timeout=10) as response:
        if response.status != 200:
            raise AssertionError(f"{path}: HTTP {response.status}")
        return response.read()


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    args = parser.parse_args(argv)

    site_dir = args.site
    release = json.loads((site_dir / manifest.MANIFEST_NAME).read_text(encoding="utf-8"))

    httpd, port = serve(site_dir)
    base = f"http://127.0.0.1:{port}"
    failures: list[str] = []

    try:
        index = get(base, "index.html")

        if b"Content-Security-Policy" not in index:
            failures.append("index.html does not declare a Content-Security-Policy")
        if OFFSITE_RE.search(index):
            failures.append("index.html references an off-origin asset")

        # Every file the manifest lists must be served, byte for byte.
        for entry in release["files"]:
            if entry["path"] == ".nojekyll":
                continue
            payload = get(base, entry["path"])
            if sha256_hex(payload) != entry["sha256"]:
                failures.append(f"{entry['path']}: served bytes do not match the manifest")

        # Everything the shell points at must resolve.
        referenced = set(re.findall(rb'(?:src|href|data-[a-z]+)="([^"]+\.(?:css|js|json))"', index))
        for name in sorted(referenced):
            target = name.decode("utf-8")
            try:
                payload = get(base, target)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{target}: referenced by the shell but not served ({exc})")
                continue
            if target.endswith(".json"):
                try:
                    json.loads(payload)
                except json.JSONDecodeError as exc:
                    failures.append(f"{target}: not valid JSON ({exc})")
            if target.endswith(".js") and OFFSITE_RE.search(payload):
                failures.append(f"{target}: contains an off-origin reference")

        counts = release.get("counts", {})
        articles = json.loads(get(base, [e["path"] for e in release["files"]
                                         if e["path"].startswith("articles-")][0]))
        if len(articles.get("articles", [])) != counts.get("articles"):
            failures.append("articles payload does not match the manifest count")

        print(f"served    : {base}")
        print(f"files     : {len(release['files'])}")
        print(f"articles  : {counts.get('articles')}")
        print(f"headlines : {counts.get('headlines')}")
        print(f"referenced: {len(referenced)} assets resolved")
    finally:
        httpd.shutdown()
        httpd.server_close()

    for failure in failures:
        print(f"error     : {failure}", file=sys.stderr)
    if failures:
        print(f"\nFAILED with {len(failures)} problem(s)", file=sys.stderr)
        return 1
    print("\nsmoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
