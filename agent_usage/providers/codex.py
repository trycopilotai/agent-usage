"""Codex usage, from the first party usage route.

One quirk is pinned by a test. This provider reports the
reset as seconds remaining rather than as an instant, so it
is the one adapter that does no clock arithmetic. Treating
that number as a timestamp puts the reset in 1970.
"""

from __future__ import annotations

import time
from typing import Any

from .. import contract
from . import base, credentials

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
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


def parse(body: Any, now: float) -> contract.Observation:
    if not isinstance(body, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    limits = body.get("rate_limit")
    if not isinstance(limits, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    windows: list[contract.Window] = []
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
            contract.Window(label=label, used_percent=percent, resets_in_seconds=remaining)
        )
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
