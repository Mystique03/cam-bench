#!/usr/bin/env python3
"""Offline check for cam_bench.server's routing - no camera needed, the grab loop
just idles with no backend open. Guards the live view's cache-busted frame URL:
the page requests /frame.jpg?t=<ms>, and routing on the raw request line sent
those to the static file handler, which 404'd every frame while the stats
endpoint (fetched without a query) kept working. Run: python tests/test_server_routes.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cam_bench.server import start_server
from cam_bench.session import Session


def check(name: str, condition: bool) -> bool:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    return condition


def get(base: str, path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(base + path, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "")


def main() -> int:
    all_ok = True
    httpd = start_server(Session(), host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, ctype = get(base, "/frame.jpg?t=1755600000000")
        all_ok &= check("cache-busted /frame.jpg?t=... reaches the frame endpoint",
                         status == 200 and ctype == "image/jpeg")

        status, ctype = get(base, "/frame.jpg")
        all_ok &= check("bare /frame.jpg still reaches the frame endpoint",
                         status == 200 and ctype == "image/jpeg")

        status, ctype = get(base, "/stats.json?t=1")
        all_ok &= check("a query string on /stats.json is ignored too",
                         status == 200 and ctype == "application/json")

        status, ctype = get(base, "/")
        all_ok &= check("/ serves the UI", status == 200 and ctype == "text/html")

        status, _ = get(base, "/index.html?v=2")
        all_ok &= check("static files tolerate a query string", status == 200)

        status, _ = get(base, "/../cam_bench/server.py?t=1")
        all_ok &= check("path traversal is still rejected with a query string",
                         status == 404)
    finally:
        httpd._cam_bench_stop.set()
        httpd.shutdown()
        httpd.server_close()

    print()
    print("ALL PASS" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
