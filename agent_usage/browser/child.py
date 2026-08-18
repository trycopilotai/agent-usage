"""Drive one browser page and print one JSON line.

This runs as a separate short lived process so the service
never holds a browser open, and so a hung page is killed by a
deadline rather than waited on. Playwright is imported inside
the function that needs it, so the package installs and runs
with no browser present at all.

It prints exactly one JSON object on stdout and nothing else.
Cookies, storage, headers, page HTML, and DOM snapshots never
appear in that object. A screenshot, when one is requested,
is written to a path given on the command line and never
returned in band, because this process communicates through a
pipe that a parent reads into memory.

This tool never opens the browser you use. It keeps its own
profile directory and an explicit login step populates it.
Copying a live browser profile is how a usage reader ends up
holding every cookie you own.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .. import contract
from . import extract

NAVIGATE_TIMEOUT_MS = 30000
SETTLE_TIMEOUT_MS = 15000
LOGIN_POLL_SECONDS = 180


def emit(document: dict[str, Any]) -> int:
    """Print the single result line and return an exit code."""
    sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0 if document.get("windows") else 1


def _context_options(headed: bool) -> dict[str, Any]:
    return {
        "headless": not headed,
        "viewport": {"width": 1280, "height": 900},
        "args": ["--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
    }


def run(
    provider: str,
    profile_dir: Path,
    *,
    headed: bool = False,
    wait_for_login: bool = False,
    screenshot: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    moment = time.time() if now is None else now
    page_url = extract.USAGE_PAGES.get(provider)
    if page_url is None:
        return {"error": contract.ERROR_UNSUPPORTED}
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        return {"error": contract.ERROR_BROWSER_UNAVAILABLE}

    captured: list[Any] = []
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir), **_context_options(headed)
            )
        except Exception:
            # Playwright installed without its browser download
            # is still "no browser", not an unreachable
            # provider. The latter sends a reader to debug a
            # network that is fine.
            return {"error": contract.ERROR_BROWSER_UNAVAILABLE}
        try:
            page = context.new_page()

            def on_response(response: Any) -> None:
                try:
                    if not extract.matches_usage_response(provider, response.url):
                        return
                    captured.append(response.json())
                except Exception:
                    # A body that is not JSON is simply not a
                    # usage response. Never let it end the run.
                    return

            page.on("response", on_response)
            page.goto(page_url, wait_until="domcontentloaded", timeout=NAVIGATE_TIMEOUT_MS)
            if wait_for_login:
                _wait_for_login(provider, captured, page, moment)
            page.wait_for_timeout(SETTLE_TIMEOUT_MS if not headed else 2000)
            text = _body_text(page)
            if screenshot is not None:
                _capture(page, screenshot)
            return _result(provider, captured, text, moment)
        finally:
            context.close()


def _signed_in(provider: str, captured: list[Any], page: Any, now: float) -> bool:
    """True once the page actually shows this provider's usage.

    Cookie presence is not the signal. Navigating to a signed
    out page sets cookies too, so waiting for "any cookie"
    returned immediately and the window closed before the
    operator could type anything.
    """
    document = _result(provider, captured, _body_text(page), now)
    return bool(document.get("windows"))


def _wait_for_login(provider: str, captured: list[Any], page: Any, now: float) -> None:
    """Hold the visible window open until usage appears.

    Returns early the moment a reading is possible, so an
    already signed in profile does not sit here for minutes.
    """
    deadline = time.time() + LOGIN_POLL_SECONDS
    while time.time() < deadline:
        if _signed_in(provider, captured, page, now):
            return
        page.wait_for_timeout(2000)


def _body_text(page: Any) -> str:
    try:
        return page.inner_text("body")
    except Exception:
        return ""


def _capture(page: Any, destination: Path) -> None:
    """Write the latest portal screenshot, or say nothing.

    A failed capture never fails a usage read. The screenshot
    is a convenience for a human looking at a page that
    changed shape, not part of the answer.
    """
    try:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        page.screenshot(path=str(destination), full_page=True)
    except Exception:
        return


def _result(provider: str, captured: list[Any], text: str, now: float) -> dict[str, Any]:
    """Prefer the provider's own JSON over the rendered text."""
    for body in captured:
        observation = _parse_first_party(provider, body, now)
        if observation is not None and observation.answered:
            document = observation.to_dict()
            document["source"] = contract.SOURCE_BROWSER_JSON
            return document
    return extract.observation_from_text(provider, text, now).to_dict()


def _parse_first_party(provider: str, body: Any, now: float) -> contract.Observation | None:
    from ..providers import registry

    try:
        adapter = registry.adapter(provider)
    except registry.UnknownProvider:
        return None
    parse = getattr(adapter, "parse", None)
    if parse is None:
        return None
    try:
        return parse(body, now)
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read one provider usage page.")
    parser.add_argument("--provider", required=True, choices=extract.BROWSER_PROVIDERS)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--wait-for-login", action="store_true")
    parser.add_argument("--screenshot", type=Path, default=None)
    arguments = parser.parse_args(argv)
    try:
        document = run(
            arguments.provider,
            arguments.profile_dir,
            headed=arguments.headed,
            wait_for_login=arguments.wait_for_login,
            screenshot=arguments.screenshot,
        )
    except Exception as error:  # pragma: no cover
        document = {"error": contract.ERROR_UNAVAILABLE, "kind": type(error).__name__}
    return emit(document)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
