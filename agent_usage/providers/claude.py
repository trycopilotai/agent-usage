"""Claude usage, from the first party OAuth usage route.

One quirk is pinned by a test. The per model weekly windows
are reported at zero utilization when the model has not been
touched, and a zero there means untouched rather than
measured, so those windows are omitted. The overall five
hour and seven day windows are always reported, including at
zero, because there a zero is a measurement.

An expired access token is renewed rather than reported. The
credential is short lived and nothing else on a collector
host refreshes it, so reporting the expiry means this
provider goes dark twice a day and stays dark. See
`renewal.py` for why that renewal has to store its result.
"""

from __future__ import annotations

import time
from typing import Any

from .. import contract
from . import base, credentials, renewal

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"

# Overall pools, always reported even at zero.
OVERALL_WINDOWS = (("five_hour", "5-hour"), ("seven_day", "7-day"))

# Per model pools, omitted at zero. See the module docstring.
PER_MODEL_WINDOWS = (
    ("seven_day_opus", "7-day opus"),
    ("seven_day_sonnet", "7-day sonnet"),
)

PROVIDER = "claude"


def collect(now: float | None = None, **kwargs: Any) -> contract.Observation:
    moment = time.time() if now is None else now
    credential = credentials.claude(**kwargs)
    if not credential.present:
        return contract.failed(PROVIDER, contract.ERROR_NO_CREDENTIAL, now=moment)
    if credential.expired:
        credential = _renewed(credential, moment, **kwargs)
    if credential.expired:
        return contract.failed(PROVIDER, contract.ERROR_CREDENTIAL_EXPIRED, now=moment)
    headers = {
        "Authorization": "Bearer " + str(credential.token),
        "anthropic-beta": OAUTH_BETA,
        "Accept": "application/json",
    }
    try:
        body = base.get_json(USAGE_URL, headers)
    except base.HttpFailure as failure:
        return contract.failed(PROVIDER, failure.code, now=moment)
    return parse(body, moment)


def _renewed(
    credential: credentials.Credential, now: float, **kwargs: Any
) -> credentials.Credential:
    """Spend the refresh token, then find the credential again.

    Only a credential that came from a file is renewed. On
    macOS the keychain is the client's own store, and the file
    this could write is not what the client reads back, so
    renewing there would report success while changing nothing
    that matters.

    The credential is re-read rather than assembled from the
    renewal's return, so that what this adapter goes on to use
    is what actually landed on disk.
    """
    if credential.origin != "file":
        return credential
    if not renewal.renew_claude(home=kwargs.get("home"), now=now):
        return credential
    return credentials.claude(**kwargs)


def parse(body: Any, now: float) -> contract.Observation:
    if not isinstance(body, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    windows: list[contract.Window] = []
    for key, label in OVERALL_WINDOWS:
        entry = body.get(key)
        if not isinstance(entry, dict):
            continue
        percent = base.clamp_percent(entry.get("utilization"))
        if percent is None:
            continue
        windows.append(
            contract.Window(
                label=label,
                used_percent=percent,
                resets_in_seconds=base.seconds_until(entry.get("resets_at"), now),
            )
        )
    for key, label in PER_MODEL_WINDOWS:
        entry = body.get(key)
        if not isinstance(entry, dict):
            continue
        percent = base.clamp_percent(entry.get("utilization"))
        if percent is None or percent <= 0.0:
            continue
        windows.append(
            contract.Window(
                label=label,
                used_percent=percent,
                resets_in_seconds=base.seconds_until(entry.get("resets_at"), now),
            )
        )
    if not windows:
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    return contract.Observation(
        provider=PROVIDER,
        collected_at=now,
        windows=tuple(windows),
        credits=_credits(body),
        source=contract.SOURCE_API,
    )


def _credits(body: Any) -> contract.Credits:
    entry = body.get("extra_usage") if isinstance(body, dict) else None
    if not isinstance(entry, dict):
        return contract.Credits(contract.CREDIT_UNAVAILABLE, "")
    if entry.get("enabled") is False:
        return contract.Credits(contract.CREDIT_OFF, "extra usage disabled")
    used = base.number(entry.get("used"))
    cap = base.number(entry.get("cap"))
    if used is not None and cap is not None and cap > 0:
        if used >= cap:
            return contract.Credits(contract.CREDIT_EXHAUSTED, "extra usage cap reached")
        if used > 0:
            return contract.Credits(contract.CREDIT_ACTIVE, "extra usage engaged")
        return contract.Credits(contract.CREDIT_AVAILABLE, "extra usage enabled, unused")
    return contract.Credits(contract.CREDIT_UNAVAILABLE, "")
