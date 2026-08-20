"""Turn a provider's own JSON or rendered text into windows.

Two paths, tried in that order. When the page makes its own
request for usage, that response is the provider's first
party JSON and the existing adapter parses it.

Only when no such response is seen does this fall back to
reading the rendered text. That path is lossy and is
labelled differently in the observation, so a reader always
knows which one produced a number.

This module holds no browser code, which is what lets the
lossy path be tested without launching anything.
"""

from __future__ import annotations

import re
from typing import Any

from .. import contract

# URL fragments whose responses carry first party usage JSON.
USAGE_RESPONSE_FRAGMENTS = {
    "claude": ("/api/oauth/usage", "/api/organizations/", "/settings/usage"),
    "codex": ("/backend-api/wham/usage", "/backend-api/usage"),
    "kimi": ("/coding/v1/usages", "/v1/usages"),
    "grok": ("/v1/billing", "/rest/usage", "/api/usage"),
}

# The page a provider renders its usage on.
USAGE_PAGES = {
    "claude": "https://claude.ai/settings/usage",
    "codex": "https://chatgpt.com/codex/settings/usage",
    "kimi": "https://www.kimi.com/code/console",
    "grok": "https://grok.com/settings/usage",
}

BROWSER_PROVIDERS = tuple(sorted(USAGE_PAGES))

_PERCENT_WITH_LABEL = re.compile(
    r"(?P<label>\d+\s*(?:hour|day|week|month)s?)[^%\n]{0,40}?(?P<percent>\d{1,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_USED_OF_LIMIT = re.compile(
    r"(?P<used>[\d,]+)\s*(?:/|of)\s*(?P<limit>[\d,]+)",
    re.IGNORECASE,
)
_RESET_IN = re.compile(
    r"resets?\s+in\s+(?P<amount>\d+)\s*(?P<unit>minute|hour|day|week)s?",
    re.IGNORECASE,
)

_UNIT_SECONDS = {
    "minute": 60.0,
    "hour": 3600.0,
    "day": 86400.0,
    "week": 604800.0,
}


def normalize_label(raw: str) -> str:
    """Fold "5 Hours" and "5-hour" onto one spelling."""
    text = " ".join(raw.lower().split())
    match = re.match(r"(\d+)\s*(minute|hour|day|week|month)s?", text)
    if match is None:
        return text
    return match.group(1) + "-" + match.group(2)


def resets_in_from_text(text: str) -> float | None:
    match = _RESET_IN.search(text or "")
    if match is None:
        return None
    amount = float(match.group("amount"))
    return amount * _UNIT_SECONDS.get(match.group("unit").lower(), 0.0)


def windows_from_text(text: str) -> tuple[contract.Window, ...]:
    """Read whatever the rendered page states plainly.

    Nothing is inferred. A page that states no percentage
    produces no window, because an absent number must not
    become a zero.
    """
    if not isinstance(text, str) or not text:
        return ()
    resets = resets_in_from_text(text)
    found: dict[str, contract.Window] = {}
    for match in _PERCENT_WITH_LABEL.finditer(text):
        label = normalize_label(match.group("label"))
        percent = float(match.group("percent"))
        if not 0.0 <= percent <= 100.0:
            continue
        if label in found:
            continue
        found[label] = contract.Window(
            label=label,
            used_percent=percent,
            resets_in_seconds=resets,
        )
    return tuple(found[key] for key in sorted(found))


def windows_from_used_of_limit(text: str) -> tuple[contract.Window, ...]:
    """Handle pages that show a count rather than a percent."""
    match = _USED_OF_LIMIT.search(text or "")
    if match is None:
        return ()
    used = float(match.group("used").replace(",", ""))
    limit = float(match.group("limit").replace(",", ""))
    if limit <= 0:
        return ()
    return (
        contract.Window(
            label="reported",
            used_percent=max(0.0, min(100.0, used / limit * 100.0)),
            resets_in_seconds=resets_in_from_text(text),
            remaining=max(0.0, limit - used),
            limit=limit,
        ),
    )


def matches_usage_response(provider: str, url: str) -> bool:
    for fragment in USAGE_RESPONSE_FRAGMENTS.get(provider, ()):  # pragma: no branch
        if fragment in (url or ""):
            return True
    return False


def observation_from_text(provider: str, text: str, now: float) -> contract.Observation:
    windows = windows_from_text(text) or windows_from_used_of_limit(text)
    if not windows:
        return contract.failed(
            provider,
            contract.ERROR_BROWSER_SESSION_MISSING,
            now=now,
            source=contract.SOURCE_BROWSER_TEXT,
        )
    return contract.Observation(
        provider=provider,
        collected_at=now,
        windows=windows,
        source=contract.SOURCE_BROWSER_TEXT,
    )
