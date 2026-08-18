"""Grok billing, from the first party billing route.

Two quirks are pinned by tests. Numeric fields arrive as
bare numbers, as strings, and wrapped in a single key object,
all meaning the same thing. And this provider reports one
monthly billing figure rather than rolling windows, so the
observation carries exactly one window and never pretends to
a five hour pool it was never told about.
"""

from __future__ import annotations

import time
from typing import Any

from .. import contract
from . import base, credentials

BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing"
PROVIDER = "grok"


def collect(now: float | None = None, **kwargs: Any) -> contract.Observation:
    moment = time.time() if now is None else now
    credential = credentials.grok(**kwargs)
    if not credential.present:
        return contract.failed(PROVIDER, contract.ERROR_NO_CREDENTIAL, now=moment)
    headers = {
        "Authorization": "Bearer " + str(credential.token),
        "Accept": "application/json",
    }
    try:
        body = base.get_json(BILLING_URL, headers)
    except base.HttpFailure as failure:
        return contract.failed(PROVIDER, failure.code, now=moment)
    return parse(body, moment)


def parse(body: Any, now: float) -> contract.Observation:
    if not isinstance(body, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    config = body.get("config")
    if not isinstance(config, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    limit = base.number(config.get("monthlyLimit"))
    used = base.number(config.get("used"))
    if limit is None or used is None or limit <= 0:
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    percent = max(0.0, min(100.0, used / limit * 100.0))
    window = contract.Window(
        label="monthly",
        used_percent=percent,
        resets_in_seconds=base.seconds_until(config.get("billingPeriodEnd"), now),
        remaining=max(0.0, limit - used),
        limit=limit,
    )
    return contract.Observation(
        provider=PROVIDER,
        collected_at=now,
        windows=(window,),
        plan="",
        credits=_credits(config, used),
        source=contract.SOURCE_API,
    )


def _credits(config: Any, used: float) -> contract.Credits:
    cap = base.number(config.get("onDemandCap")) if isinstance(config, dict) else None
    if cap is None:
        return contract.Credits(contract.CREDIT_UNAVAILABLE, "")
    if cap <= 0:
        return contract.Credits(contract.CREDIT_OFF, "on demand disabled")
    spent = base.number(config.get("onDemandUsed")) or 0.0
    if spent >= cap:
        return contract.Credits(contract.CREDIT_EXHAUSTED, "on demand cap reached")
    if spent > 0:
        return contract.Credits(contract.CREDIT_ACTIVE, "on demand engaged")
    return contract.Credits(contract.CREDIT_AVAILABLE, "on demand enabled, unused")
