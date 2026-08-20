"""Shared transport and parsing for the HTTP collectors.

One request, one deadline, no retries. A usage read that has
to be retried is a usage read that should report that it
could not answer, because the caller is deciding whether to
start work and a slow certain answer is worse than a fast
uncertain one.

There is no exception left. The one adapter that retried, and
documented why at its call site, has been removed.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request
from typing import Any

from .. import contract

HTTP_TIMEOUT_SECONDS = 15


class HttpFailure(Exception):
    """A transport failure already reduced to a closed code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def get_json(url: str, headers: dict[str, str]) -> Any:
    """GET one JSON document, or raise a closed error code.

    Exception text is deliberately discarded. The string form
    of a urllib error carries the URL, and these URLs carry
    account identifiers.
    """
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise HttpFailure(_status_code(error.code)) from None
    except (urllib.error.URLError, OSError):
        raise HttpFailure(contract.ERROR_UNAVAILABLE) from None
    except ValueError:
        raise HttpFailure(contract.ERROR_MALFORMED) from None


def _status_code(status: int) -> str:
    if status in (401, 403):
        return contract.ERROR_UNAUTHORIZED
    if status == 429:
        return contract.ERROR_RATE_LIMITED
    return contract.ERROR_UNAVAILABLE


def window_label(minutes: float) -> str:
    """Name a window from its duration, not its position.

    Providers move their windows. A label taken from where a
    window sits in the response says nothing about how long it
    covers, and goes quietly wrong the day the provider
    reshuffles them.
    """
    if minutes <= 0:
        return "window"
    if minutes % (60 * 24 * 7) == 0:
        return str(int(minutes // (60 * 24 * 7))) + "-week"
    if minutes % (60 * 24) == 0:
        return str(int(minutes // (60 * 24))) + "-day"
    if minutes % 60 == 0:
        return str(int(minutes // 60)) + "-hour"
    return str(int(minutes)) + "-minute"


def number(value: Any) -> float | None:
    """Coerce the shapes providers actually send.

    Values arrive as numbers, as numeric strings, and wrapped
    in a single key object. All three mean the same thing.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("val", "value", "amount"):
            if key in value:
                return number(value[key])
    return None


def seconds_until(stamp: Any, now: float) -> float | None:
    """Seconds from now until an ISO 8601 instant."""
    if not isinstance(stamp, str) or not stamp:
        return None
    text = stamp.strip().replace("Z", "+00:00")
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.timestamp() - now


def seconds_until_epoch_ms(value: Any, now: float) -> float | None:
    """Seconds until an instant given in epoch milliseconds."""
    milliseconds = number(value)
    if milliseconds is None:
        return None
    return milliseconds / 1000.0 - now


def percent_from_used_and_limit(used: Any, limit: Any) -> float | None:
    """Percent used, from a consumed amount and a limit.

    Several providers report those two and no percentage.
    Both are required; either one missing declines.
    """
    used_value = number(used)
    limit_value = number(limit)
    if used_value is None or limit_value is None:
        return None
    if limit_value <= 0:
        return None
    return max(0.0, min(100.0, used_value / limit_value * 100.0))


def clamp_percent(value: Any) -> float | None:
    parsed = number(value)
    if parsed is None:
        return None
    return max(0.0, min(100.0, parsed))
