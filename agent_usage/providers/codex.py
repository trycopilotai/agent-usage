"""Codex usage, from the first party usage route.

Two quirks are pinned by tests. This provider reports the
reset as seconds remaining rather than as an instant, so it
is the one adapter that does no clock arithmetic. Treating
that number as a timestamp puts the reset in 1970.

And the window a key holds is not fixed: `primary_window` has
been observed carrying a five hour window and, later, a
weekly one on the same account. Every window states its own
`limit_window_seconds`, so the label is read from that and
the key is used only as a fallback for a response that omits
it.

The response also carries `additional_rate_limits`, a list of
separately metered features with their own pools. Those are
read too. An account has been observed with the top level
pool at zero percent while a named feature pool sat at a
hundred, which reads as full headroom when there is none.
"""

from __future__ import annotations

import time
from typing import Any

from .. import contract
from . import base, credentials

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
# The names are the historical meaning of each key, kept only
# for a response that does not state its window length.
WINDOWS = (("primary_window", "5-hour"), ("secondary_window", "weekly"))
PROVIDER = "codex"


def collect(now: float | None = None, **kwargs: Any) -> contract.Observation:
    moment = time.time() if now is None else now
    credential = credentials.codex(**kwargs)
    if not credential.present:
        return contract.failed(PROVIDER, contract.ERROR_NO_CREDENTIAL, now=moment)
    headers = {
        "Authorization": "Bearer " + str(credential.token),
        "ChatGPT-Account-Id": credential.account or "",
        "Accept": "application/json",
    }
    try:
        body = base.get_json(USAGE_URL, headers)
    except base.HttpFailure as failure:
        return contract.failed(PROVIDER, failure.code, now=moment)
    return parse(body, moment)


def window_label(entry: dict, fallback: str) -> str:
    """What this window covers, from the window itself.

    `limit_window_seconds` is the provider's own statement of
    the period. Reading it means a window that moves between
    keys is still named correctly; falling back to the key name
    keeps a response that omits the field working as before.
    """
    seconds = base.number(entry.get("limit_window_seconds"))
    if seconds is None or seconds <= 0:
        return fallback
    return base.window_label(seconds / 60.0)


def _pool_windows(limits: Any, prefix: str = "") -> list[contract.Window]:
    """Every window in one rate_limit object.

    `prefix` names the metered feature a pool belongs to, so a
    card carrying several pools says which limit each row is
    about rather than showing two rows called "1-week".
    """
    windows: list[contract.Window] = []
    if not isinstance(limits, dict):
        return windows
    for key, label in WINDOWS:
        entry = limits.get(key)
        if not isinstance(entry, dict):
            continue
        percent = base.clamp_percent(entry.get("used_percent"))
        if percent is None:
            continue
        # Already a duration. Do not convert.
        remaining = base.number(entry.get("reset_after_seconds"))
        windows.append(
            contract.Window(
                label=prefix + window_label(entry, label),
                used_percent=percent,
                resets_in_seconds=remaining,
            )
        )
    return windows


def _additional_windows(body: dict) -> list[contract.Window]:
    """The pools of separately metered features.

    Each entry names its feature and carries a rate_limit of
    the same shape as the top level one. They are reported
    because an exhausted feature pool is a real limit on the
    work this account can do, and leaving it out shows
    headroom that does not exist.
    """
    entries = body.get("additional_rate_limits")
    if not isinstance(entries, list):
        return []
    windows: list[contract.Window] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("limit_name")
        if not isinstance(name, str) or not name:
            name = entry.get("metered_feature")
        if not isinstance(name, str) or not name:
            continue
        windows.extend(_pool_windows(entry.get("rate_limit"), name + " "))
    return windows


def parse(body: Any, now: float) -> contract.Observation:
    if not isinstance(body, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    limits = body.get("rate_limit")
    if not isinstance(limits, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    windows = _pool_windows(limits)
    windows.extend(_additional_windows(body))
    if not windows:
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    plan = body.get("plan_type")
    return contract.Observation(
        provider=PROVIDER,
        collected_at=now,
        windows=tuple(windows),
        plan=plan if isinstance(plan, str) else "",
        credits=contract.Credits(contract.CREDIT_UNAVAILABLE, ""),
        source=contract.SOURCE_API,
    )
