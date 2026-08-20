#!/usr/bin/env python3
"""Emit the social preview as deterministic SVG.

The card shows the one thing the tool exists to answer, five
limits and how much of each is gone, so a reader who never
opens the README knows what it does. The numbers are the
same invented ones the demo uses.
"""

from __future__ import annotations

import os
import sys

WIDTH, HEIGHT = 1280, 640
BACKGROUND = "#0d1117"
PANEL = "#161b22"
TEXT = "#f0f6fc"
MUTED = "#8b949e"
TRACK = "#21262d"

# The demo's synthetic readings. Nothing here is a real quota.
ROWS = [
    ("claude", 40.0, "#58a6ff"),
    ("codex", 12.5, "#3fb950"),
    ("grok", None, None),
    ("kimi", None, None),
]


def bar(index: int, name: str, percent: float | None, colour: str | None) -> list[str]:
    top = 250 + index * 62
    parts = [
        f'  <text x="96" y="{top + 26}" fill="{TEXT}" font-size="26" '
        f'font-family="SFMono-Regular, Menlo, monospace">{name}</text>',
        f'  <rect x="260" y="{top}" width="820" height="34" rx="17" fill="{TRACK}"/>',
    ]
    if percent is None:
        parts.append(
            f'  <text x="276" y="{top + 25}" fill="{MUTED}" font-size="21" '
            f'font-family="SFMono-Regular, Menlo, monospace">no answer</text>'
        )
        return parts
    filled = int(820 * percent / 100.0)
    parts.append(
        f'  <rect x="260" y="{top}" width="{filled}" height="34" rx="17" fill="{colour}"/>'
    )
    parts.append(
        f'  <text x="1104" y="{top + 26}" fill="{TEXT}" font-size="24" '
        f'font-family="SFMono-Regular, Menlo, monospace">{percent:.1f}%</text>'
    )
    return parts


def render() -> str:
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'  <rect width="{WIDTH}" height="{HEIGHT}" fill="{BACKGROUND}"/>',
        f'  <rect x="48" y="48" width="{WIDTH - 96}" height="{HEIGHT - 96}" rx="20" fill="{PANEL}"/>',
        f'  <text x="96" y="146" fill="{TEXT}" font-size="52" font-weight="600" '
        f'font-family="Helvetica, Arial, sans-serif">agent-usage</text>',
        f'  <text x="96" y="196" fill="{MUTED}" font-size="26" '
        f'font-family="Helvetica, Arial, sans-serif">'
        f"How much of each AI provider&#8217;s limit is used, and when it resets.</text>",
    ]
    for index, (name, percent, colour) in enumerate(ROWS):
        lines.extend(bar(index, name, percent, colour))
    lines.append(
        f'  <text x="1104" y="222" fill="{MUTED}" font-size="18" '
        f'font-family="SFMono-Regular, Menlo, monospace">used</text>'
    )
    lines.append(
        f'  <text x="96" y="{HEIGHT - 74}" fill="{MUTED}" font-size="20" '
        f'font-family="Helvetica, Arial, sans-serif">'
        f"Missing is never zero. A provider that did not answer says so.</text>"
    )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    destination = os.path.join(root, "assets", "social-preview.svg")
    rendered = render()
    if "--check" in sys.argv:
        with open(destination, "r", encoding="utf-8") as handle:
            if handle.read() != rendered:
                sys.stderr.write("social preview differs from its generator\n")
                return 1
        sys.stdout.write("social preview matches its generator\n")
        return 0
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    sys.stdout.write("wrote " + destination + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
