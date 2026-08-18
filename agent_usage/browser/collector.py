"""Run the browser child under a deadline and a cooldown.

The parent never imports Playwright and never holds a page.
It starts the child in its own process group, waits a bounded
time, and kills the whole group if the deadline passes, so a
page that hangs cannot wedge the caller.

A browser read is expensive and visible to the provider, so
one provider is read at most once per cooldown. Falling back
to a browser on every failed API call turns a rate limit into
a scrape loop.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .. import config, contract
from . import extract

CHILD_TIMEOUT_SECONDS = 120
# A headed login holds the window open for the operator, so
# the parent must outlast the child's own wait rather than
# killing the window while someone is still typing.
LOGIN_TIMEOUT_SECONDS = 240
COOLDOWN_SECONDS = 15 * 60


def _read_cooldown(path: Path) -> dict[str, float]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict):
        return {}
    return {key: float(value) for key, value in document.items() if isinstance(value, (int, float))}


def _write_cooldown(path: Path, document: dict[str, float]) -> None:
    config.ensure_private(path.parent)
    temporary = path.with_suffix(".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(document, handle, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def cooling_down(provider: str, now: float, path: Path) -> bool:
    return _read_cooldown(path).get(provider, 0.0) > now


def mark_attempt(provider: str, now: float, path: Path) -> None:
    document = _read_cooldown(path)
    document[provider] = now + COOLDOWN_SECONDS
    _write_cooldown(path, document)


def child_argv(
    provider: str,
    profile_dir: Path,
    *,
    headed: bool,
    wait_for_login: bool,
    screenshot: Path | None,
) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "agent_usage.browser.child",
        "--provider",
        provider,
        "--profile-dir",
        str(profile_dir),
    ]
    if headed:
        argv.append("--headed")
    if wait_for_login:
        argv.append("--wait-for-login")
    if screenshot is not None:
        argv.extend(["--screenshot", str(screenshot)])
    return argv


def _run_child(argv: list[str], timeout: float) -> str:
    """Return the child's single stdout line, or an empty one."""
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    except OSError:
        return ""
    try:
        stdout, _ = process.communicate(timeout=timeout)
        return stdout or ""
    except subprocess.TimeoutExpired:
        _kill_group(process)
        return ""


def _kill_group(process: Any) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.communicate(timeout=5)
    except Exception:
        pass


def collect(
    provider: str,
    *,
    now: float | None = None,
    headed: bool = False,
    wait_for_login: bool = False,
    capture_screenshot: bool = False,
    respect_cooldown: bool = True,
    environ: dict[str, str] | None = None,
    runner: Any = None,
) -> contract.Observation:
    """Read one provider through a browser, or decline.

    ``capture_screenshot`` is off by default. See the README
    for what a screenshot of a signed in portal contains.

    ``respect_cooldown`` exists for ``login``. The cap is
    there to stop an automatic fallback from scraping in a
    loop, and applying it to an operator who was just told to
    sign in blocks the only documented fix for fifteen
    minutes.
    """
    moment = time.time() if now is None else now
    if provider not in extract.BROWSER_PROVIDERS:
        return contract.failed(provider, contract.ERROR_UNSUPPORTED, now=moment)
    kwargs = {} if environ is None else {"environ": environ}
    cooldown = config.cooldown_path(**kwargs)
    if respect_cooldown and cooling_down(provider, moment, cooldown):
        return contract.failed(
            provider, contract.ERROR_COOLING_DOWN, now=moment, source=contract.SOURCE_BROWSER_JSON
        )
    profile = config.browser_profile_dir(provider, **kwargs)
    screenshot = config.screenshot_path(provider, **kwargs) if capture_screenshot else None
    argv = child_argv(
        provider,
        profile,
        headed=headed,
        wait_for_login=wait_for_login,
        screenshot=screenshot,
    )
    if respect_cooldown:
        mark_attempt(provider, moment, cooldown)
    execute = _run_child if runner is None else runner
    deadline = LOGIN_TIMEOUT_SECONDS if wait_for_login else CHILD_TIMEOUT_SECONDS
    raw = execute(argv, deadline)
    return interpret(provider, raw, moment)


def interpret(provider: str, raw: str, now: float) -> contract.Observation:
    """Turn the child's one line into an observation.

    Anything unparseable is a failed read, never a partial
    one. A child that dies mid write must not produce a
    number that looks measured.
    """
    line = (raw or "").strip().splitlines()
    if not line:
        return contract.failed(
            provider,
            contract.ERROR_BROWSER_UNAVAILABLE,
            now=now,
            source=contract.SOURCE_BROWSER_JSON,
        )
    try:
        document = json.loads(line[-1])
    except ValueError:
        return contract.failed(
            provider, contract.ERROR_MALFORMED, now=now, source=contract.SOURCE_BROWSER_JSON
        )
    if not isinstance(document, dict):
        return contract.failed(
            provider, contract.ERROR_MALFORMED, now=now, source=contract.SOURCE_BROWSER_JSON
        )
    error = document.get("error")
    if error is not None:
        code = error if error in contract.ERROR_CODES else contract.ERROR_MALFORMED
        return contract.failed(provider, code, now=now, source=contract.SOURCE_BROWSER_JSON)
    windows = _windows(document.get("windows"))
    if not windows:
        return contract.failed(
            provider,
            contract.ERROR_BROWSER_SESSION_MISSING,
            now=now,
            source=contract.SOURCE_BROWSER_JSON,
        )
    source = document.get("source")
    credits = document.get("credits")
    if isinstance(credits, dict) and credits.get("state") in contract.CREDIT_STATES:
        restored = contract.Credits(credits["state"], credits.get("detail", ""))
    else:
        restored = contract.Credits()
    return contract.Observation(
        provider=provider,
        collected_at=now,
        windows=windows,
        plan=document.get("plan") if isinstance(document.get("plan"), str) else "",
        credits=restored,
        source=source if source in contract.SOURCES else contract.SOURCE_BROWSER_JSON,
    )


def _windows(raw: Any) -> tuple[contract.Window, ...]:
    if not isinstance(raw, list):
        return ()
    windows: list[contract.Window] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label")
        percent = entry.get("used_percent")
        if not isinstance(label, str) or not label:
            continue
        if isinstance(percent, bool) or not isinstance(percent, (int, float)):
            continue
        if not 0.0 <= float(percent) <= 100.0:
            continue
        windows.append(
            contract.Window(
                label=label,
                used_percent=float(percent),
                resets_in_seconds=entry.get("resets_in_seconds"),
            )
        )
    return tuple(windows)


def login(provider: str, **kwargs: Any) -> contract.Observation:
    """Open a visible window so the operator can sign in.

    Deliberately outside the cooldown. A person asking to log
    in has already been told that is the fix.
    """
    return collect(
        provider,
        headed=True,
        wait_for_login=True,
        respect_cooldown=False,
        **kwargs,
    )
