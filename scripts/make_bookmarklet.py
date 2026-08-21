#!/usr/bin/env python3
"""Build the javascript: URL a browser can hold as a bookmark.

The token is injected here rather than committed, so the file
in the repository stays a template and the secret only ever
exists on the machine that minted it.

    python3 scripts/make_bookmarklet.py --endpoint https://usage.example/api/v1/ingest

Prints one line. Make a new bookmark and paste it as the URL.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_usage import ingest  # noqa: E402


def build(source: str, endpoint: str, token: str) -> str:
    body = source.replace("__ENDPOINT__", endpoint).replace("__TOKEN__", token)
    # A bookmarklet is a URL, so everything a URL treats as
    # structure has to be escaped. quote with an empty safe
    # list is blunt and correct; the result is unreadable
    # either way.
    return "javascript:" + quote(body, safe="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        required=True,
        help="the full ingest URL, ending in /api/v1/ingest",
    )
    parser.add_argument(
        "--provider",
        default="grok",
        choices=["grok"],
        help="which bookmarklet to build",
    )
    arguments = parser.parse_args(argv)

    token = ingest.read_token()
    if token is None:
        parser.error(
            "no ingest token yet; run: agent-usage ingest-token\n"
            "expected at " + ingest.token_file_note()
        )

    source = (ROOT / "scripts" / ("bookmarklet_%s.js" % arguments.provider)).read_text(
        encoding="utf-8"
    )
    print(build(source, arguments.endpoint, token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
