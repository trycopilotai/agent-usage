"""The boundary: what may leave a collector at all.

This is an allowlist, not a denylist. A field that is not
named here does not reach the store, the API, or a report,
so a provider that starts returning a new field cannot leak
it by default. Widening the boundary means editing this list
on purpose, and a test pins the exact membership of the
allowlist so a quiet addition fails.
"""

from __future__ import annotations

import re
from typing import Any

# Everything a stored observation may contain.
OBSERVATION_FIELDS = frozenset(
    {
        "provider",
        "collected_at",
        "source",
        "freshness",
        "plan",
        "adapter_version",
        "windows",
        "credits",
        "answered",
        "error",
        "binding_window",
    }
)

WINDOW_FIELDS = frozenset({"label", "used_percent", "resets_in_seconds", "remaining", "limit"})

CREDIT_FIELDS = frozenset({"state", "detail"})

# Shapes that must never survive, checked as a backstop even
# though no allowlisted field is expected to carry one.
_CREDENTIAL_SHAPES = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"xai-[A-Za-z0-9_-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

REDACTED = "[redacted]"


def scrub_text(value: str) -> str:
    text = value
    for pattern in _CREDENTIAL_SHAPES:
        text = pattern.sub(REDACTED, text)
    return text


def filter_window(window: Any) -> dict[str, Any]:
    if not isinstance(window, dict):
        return {}
    return {key: value for key, value in window.items() if key in WINDOW_FIELDS}


def filter_credits(credits: Any) -> dict[str, Any]:
    if not isinstance(credits, dict):
        return {"state": "unavailable", "detail": ""}
    kept = {key: value for key, value in credits.items() if key in CREDIT_FIELDS}
    detail = kept.get("detail")
    if isinstance(detail, str):
        kept["detail"] = scrub_text(detail)
    return kept


def filter_observation(document: Any) -> dict[str, Any]:
    """Drop every field the boundary does not name."""
    if not isinstance(document, dict):
        return {}
    kept: dict[str, Any] = {}
    for key, value in document.items():
        if key not in OBSERVATION_FIELDS:
            continue
        if key == "windows" and isinstance(value, list):
            kept[key] = [filter_window(entry) for entry in value]
        elif key == "binding_window":
            kept[key] = filter_window(value)
        elif key == "credits":
            kept[key] = filter_credits(value)
        elif isinstance(value, str):
            kept[key] = scrub_text(value)
        else:
            kept[key] = value
    return kept
