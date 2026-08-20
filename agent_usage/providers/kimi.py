"""Kimi usage, from the first party coding usage route.

Two quirks are pinned by tests. The limit and the remainder
arrive as strings and there is no consumed figure at all, so
the percentage is derived rather than read. And the rolling
window is identified by its declared duration rather than by
its position in the array, because the array order is not
guaranteed and matching by index silently mislabels windows.
"""

from __future__ import annotations

import time
from typing import Any

from .. import contract
from . import base, credentials

USAGE_URL = "https://api.kimi.com/coding/v1/usages"
MINUTE_UNIT = "TIME_UNIT_MINUTE"
PROVIDER = "kimi"


def collect(now: float | None = None, **kwargs: Any) -> contract.Observation:
    moment = time.time() if now is None else now
    credential = credentials.kimi(**kwargs)
    if not credential.present:
        return contract.failed(PROVIDER, contract.ERROR_NO_CREDENTIAL, now=moment)
    if credential.expired:
        return contract.failed(PROVIDER, contract.ERROR_CREDENTIAL_EXPIRED, now=moment)
    headers = {
        "Authorization": "Bearer " + str(credential.token),
        "Accept": "application/json",
    }
    try:
        body = base.get_json(USAGE_URL, headers)
    except base.HttpFailure as failure:
        return contract.failed(PROVIDER, failure.code, now=moment)
    return parse(body, moment)


# Kept as a name in this module because the quirk it serves is
# documented here, but the rule belongs to every adapter that
# reads a window duration.
window_label = base.window_label


def _quota(detail: Any, label: str, now: float) -> contract.Window | None:
    if not isinstance(detail, dict):
        return None
    limit = base.number(detail.get("limit"))
    remaining = base.number(detail.get("remaining"))
    if limit is None or remaining is None or limit <= 0:
        return None
    percent = max(0.0, min(100.0, (limit - remaining) / limit * 100.0))
    return contract.Window(
        label=label,
        used_percent=percent,
        resets_in_seconds=base.seconds_until(detail.get("resetTime"), now),
        remaining=remaining,
        limit=limit,
    )


def parse(body: Any, now: float) -> contract.Observation:
    if not isinstance(body, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    windows: list[contract.Window] = []
    entries = body.get("limits")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            window = entry.get("window")
            if not isinstance(window, dict) or window.get("timeUnit") != MINUTE_UNIT:
                continue
            minutes = base.number(window.get("duration"))
            if minutes is None:
                continue
            parsed = _quota(entry.get("detail"), window_label(minutes), now)
            if parsed is not None:
                windows.append(parsed)
    weekly = _quota(body.get("usage"), "weekly", now)
    if weekly is not None:
        windows.append(weekly)
    if not windows:
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    return contract.Observation(
        provider=PROVIDER,
        collected_at=now,
        windows=tuple(windows),
        plan=_plan(body),
        credits=_credits(body),
        source=contract.SOURCE_API,
    )


def _plan(body: Any) -> str:
    level = body.get("user") if isinstance(body, dict) else None
    if isinstance(level, dict):
        membership = level.get("membership")
        if isinstance(membership, dict):
            name = membership.get("level")
            if isinstance(name, str):
                return name.replace("LEVEL_", "").lower()
    return ""


def _credits(body: Any) -> contract.Credits:
    """This provider reports no credit object at all.

    An earlier version inferred "exhausted" from an empty
    weekly pool. That word belongs to the paid overage
    allowance, and an empty quota is a different fact about a
    different thing. Unavailable is the honest answer when the
    provider did not say.
    """
    return contract.Credits(contract.CREDIT_UNAVAILABLE, "")
