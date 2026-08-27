#!/usr/bin/env python3
"""Serve the built dashboard and stats over HTTP."""

from __future__ import annotations

import argparse
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DOCS), **kwargs)


def ensure_built() -> None:
    if not (DOCS / "index.html").exists():
        subprocess.run([sys.executable, str(ROOT / "build_pages.py")], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-build", action="store_true", help="Skip auto-build")
    args = parser.parse_args()

    if not args.no_build:
        ensure_built()

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Serving dashboard at http://{args.host}:{args.port}/")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
