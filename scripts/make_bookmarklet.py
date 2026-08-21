#!/usr/bin/env python3
"""Build the javascript: URL a browser can hold as a bookmark.

    python3 scripts/make_bookmarklet.py --dashboard https://usage.example

Prints one line. Make a new bookmark and paste it as the URL.
Both Safari and Chrome strip a javascript: URL typed into the
address bar, so it has to be saved as a bookmark to run.

Nothing secret is injected. The reading travels in a URL
fragment to a dashboard that is behind its own sign in, so the
bookmarklet needs no token and can be shared freely.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent


def build(source: str, dashboard: str) -> str:
    body = source.replace("__DASHBOARD__", dashboard.rstrip("/"))
    # A bookmarklet is a URL, so everything a URL treats as
    # structure has to be escaped. quote with an empty safe
    # list is blunt and correct; the result is unreadable
    # either way.
    return "javascript:" + quote(body, safe="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dashboard",
        required=True,
        help="where the dashboard is served, e.g. https://usage.example",
    )
    parser.add_argument(
        "--provider",
        default="grok",
        choices=["grok"],
        help="which bookmarklet to build",
    )
    arguments = parser.parse_args(argv)

    if not arguments.dashboard.startswith(("http://", "https://")):
        parser.error("--dashboard must be an absolute URL")

    source = (ROOT / "scripts" / ("bookmarklet_%s.js" % arguments.provider)).read_text(
        encoding="utf-8"
    )
    print(build(source, arguments.dashboard))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
