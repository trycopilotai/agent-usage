"""z.ai quota, from the first party monitor route.

This adapter carries the sharpest quirks in the set, and all
of them are pinned by tests.

The field names mislead. The field called ``usage`` is the
LIMIT, and ``currentValue`` is the amount consumed. Reading
them at face value inverts the answer, reporting a nearly
exhausted quota as nearly untouched.

``nextResetTime`` is epoch milliseconds, not seconds.

The window arrives as a unit code with a count. Unit 3 is
hours and unit 6 is weeks. The mapping is observed rather
than documented, so an unrecognised code is skipped rather
than guessed at.

The endpoint answers 200 with a failure in the body, so
success is checked in band rather than by status.

The accepted authorization scheme is inconsistent, so a
single 401 is retried once with the raw key. That is the one
retry in this package and it exists because the alternative
is reporting a working credential as unauthorized.
"""

from __future__ import annotations

import time
from typing import Any

from .. import contract
from . import base, credentials

QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
UNIT_HOURS = 3
UNIT_WEEKS = 6
PROVIDER = "zai"


def collect(now: float | None = None, **kwargs: Any) -> contract.Observation:
    moment = time.time() if now is None else now
    credential = credentials.zai(**kwargs)
    if not credential.present:
        return contract.failed(PROVIDER, contract.ERROR_NO_CREDENTIAL, now=moment)
    token = str(credential.token)
    try:
        body = _get(("Bearer " + token))
    except base.HttpFailure as failure:
        if failure.code != contract.ERROR_UNAUTHORIZED:
            return contract.failed(PROVIDER, failure.code, now=moment)
        try:
            body = _get(token)
        except base.HttpFailure as retry_failure:
            return contract.failed(PROVIDER, retry_failure.code, now=moment)
    return parse(body, moment)


def _get(authorization: str) -> Any:
    return base.get_json(
        QUOTA_URL,
        {"Authorization": authorization, "Accept": "application/json"},
    )


def window_label(unit: Any, count: Any) -> str | None:
    """Name a window from an observed unit code, or decline."""
    code = base.number(unit)
    number_of = base.number(count)
    if code is None:
        return None
    if int(code) == UNIT_HOURS:
        amount = 1 if number_of is None else int(number_of)
        return str(amount) + "-hour"
    if int(code) == UNIT_WEEKS:
        if number_of is None or int(number_of) == 1:
            return "weekly"
        return str(int(number_of)) + "-week"
    return None


def parse(body: Any, now: float) -> contract.Observation:
    if not isinstance(body, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    # Success lives in the body, not in the status line.
    if body.get("success") is False:
        return contract.failed(PROVIDER, contract.ERROR_UNAVAILABLE, now=now)
    data = body.get("data")
    if not isinstance(data, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    windows: list[contract.Window] = []
    entries = data.get("limits")
    if isinstance(entries, list):
        for entry in entries:
            parsed = _window(entry, now)
            if parsed is not None:
                windows.append(parsed)
    if not windows:
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    level = data.get("level")
    return contract.Observation(
        provider=PROVIDER,
        collected_at=now,
        windows=tuple(windows),
        plan=level.lower() if isinstance(level, str) else "",
        # The quota endpoint carries no credit field, so
        # nothing was said. "off" would be an assertion the
        # provider never made.
        credits=contract.Credits(contract.CREDIT_UNAVAILABLE, ""),
        source=contract.SOURCE_API,
    )


def _window(entry: Any, now: float) -> contract.Window | None:
    if not isinstance(entry, dict):
        return None
    label = window_label(entry.get("unit"), entry.get("number"))
    if label is None:
        return None
    # "usage" is the limit and "currentValue" is consumption.
    limit = base.number(entry.get("usage"))
    consumed = base.number(entry.get("currentValue"))
    percent = base.clamp_percent(entry.get("percentage"))
    if percent is None:
        percent = base.percent_from_used_and_limit(consumed, limit)
    if percent is None:
        return None
    return contract.Window(
        label=label,
        used_percent=percent,
        resets_in_seconds=base.seconds_until_epoch_ms(entry.get("nextResetTime"), now),
        remaining=None if (limit is None or consumed is None) else max(0.0, limit - consumed),
        limit=limit,
    )
