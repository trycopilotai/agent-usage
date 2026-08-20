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
separately metered features with their own pools, and
`code_review_rate_limit`, one more pool of the same shape.
All of them are read. An account has been observed with the
top level pool at zero percent while a named feature pool sat
at a hundred, which reads as full headroom when there is
none.

Every pool says which limit it belongs to, including the
account wide one. Two rows both called "1-week" that mean
different limits are worse than no rows at all, because the
reader cannot tell which of them is the one about to stop
their work.

The feature pools are marked as such, and that is what keeps
them out of the binding choice. An exhausted Spark pool is a
real limit on one capability, not a statement about the
account: reporting it as the account's governing limit says
this account can do nothing, when what is true is that it can
do everything except one thing. It is still reported and still
drawn, and `spent_features` is how a reader is told about it.
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

# What the account wide pool is called on a card that also
# carries feature pools. Without it the top level rows are the
# only ones that do not say what they limit.
OVERALL_PREFIX = "overall "

# One more pool, in its own key rather than in the list.
CODE_REVIEW_KEY = "code_review_rate_limit"
CODE_REVIEW_PREFIX = "code review "

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


def _pool_windows(
    limits: Any,
    prefix: str = "",
    scope: str = contract.SCOPE_ACCOUNT,
) -> list[contract.Window]:
    """Every window in one rate_limit object.

    `prefix` names the metered feature a pool belongs to, so a
    card carrying several pools says which limit each row is
    about rather than showing two rows called "1-week".

    `scope` says whether the pool limits the account or one
    capability inside it. The prefix is for a reader; the scope
    is for the code that has to choose which pool governs.
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
                scope=scope,
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
        windows.extend(_pool_windows(entry.get("rate_limit"), name + " ", contract.SCOPE_FEATURE))
    return windows


def _code_review_windows(body: dict) -> list[contract.Window]:
    """The code review pool, which sits in its own key.

    It is metered separately from everything in
    `additional_rate_limits` and is null on an account that has
    not used it, which is not the same as an account that has
    no such limit.
    """
    return _pool_windows(body.get(CODE_REVIEW_KEY), CODE_REVIEW_PREFIX, contract.SCOPE_FEATURE)


def parse(body: Any, now: float) -> contract.Observation:
    if not isinstance(body, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    limits = body.get("rate_limit")
    if not isinstance(limits, dict):
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    windows = _pool_windows(limits, OVERALL_PREFIX)
    windows.extend(_additional_windows(body))
    windows.extend(_code_review_windows(body))
    if not windows:
        return contract.failed(PROVIDER, contract.ERROR_MALFORMED, now=now)
    plan = body.get("plan_type")
    return contract.Observation(
        provider=PROVIDER,
        collected_at=now,
        windows=tuple(windows),
        plan=plan if isinstance(plan, str) else "",
        credits=_credits(body),
        source=contract.SOURCE_API,
    )


def _credits(body: Any) -> contract.Credits:
    """What the account can fall back on once a pool is spent.

    This response states it directly and the adapter used to
    discard it, so every codex card said credits were not
    reported when the account had been telling us all along.

    "Unlimited" and "has credits" are both headroom rather than
    spending: nothing here says a credit is being consumed
    right now, and claiming otherwise would put a card into a
    state the provider never described.
    """
    entry = body.get("credits") if isinstance(body, dict) else None
    if not isinstance(entry, dict):
        return contract.Credits(contract.CREDIT_UNAVAILABLE, "")
    if entry.get("overage_limit_reached") is True:
        return contract.Credits(contract.CREDIT_EXHAUSTED, "overage limit reached")
    if entry.get("unlimited") is True:
        return contract.Credits(contract.CREDIT_AVAILABLE, "credits unlimited")
    if entry.get("has_credits") is True:
        return contract.Credits(contract.CREDIT_AVAILABLE, "credit balance available")
    if entry.get("has_credits") is False:
        # Not "exhausted": that word belongs to an allowance
        # that was spent, and this account may never have had
        # one to spend.
        return contract.Credits(contract.CREDIT_OFF, "no credit balance")
    return contract.Credits(contract.CREDIT_UNAVAILABLE, "")
