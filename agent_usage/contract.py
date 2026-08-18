"""The observation contract every collector must satisfy.

One shape carries every provider, so the API, the CLI, and
the report never learn provider specific fields. Three rules
hold everywhere and are enforced by tests:

Missing is never zero. A provider that did not answer has no
window, rather than a window at zero percent, because zero
percent used and no answer lead a reader to opposite
decisions.

Stale never appears live. Every observation carries the
moment it was collected and the source that produced it, so
a cached read cannot be mistaken for a fresh one.

Nothing here is guessed from usage patterns. Every number
comes from what the provider said about itself, though an
adapter may convert it: several report a limit and a
remainder rather than a percentage, and the percentage is
computed from those two. Anything derived from a series of
observations over time, such as a rate, lives in `derive`
rather than in an observation.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any

SCHEMA = "trycopilotai/agent-usage/observation/v1"

# How the observation was obtained. The browser sources stay
# distinct from the API source because a reader deciding
# whether to trust a number wants to know a page was scraped.
SOURCE_API = "api"
SOURCE_BROWSER_JSON = "browser_json"
SOURCE_BROWSER_TEXT = "browser_text"

SOURCES = (
    SOURCE_API,
    SOURCE_BROWSER_JSON,
    SOURCE_BROWSER_TEXT,
)

# Freshness is a judgement about age, not a timestamp, so the
# reader does not have to do arithmetic to know what it holds.
FRESHNESS_LIVE = "live"
FRESHNESS_CACHED = "cached"
FRESHNESS_STALE = "stale"

FRESHNESS_STATES = (
    FRESHNESS_LIVE,
    FRESHNESS_CACHED,
    FRESHNESS_STALE,
)

# Credit state is a closed set. "unavailable" means the
# provider was not asked or did not say, which is different
# from "off", meaning it said there is no credit engaged.
CREDIT_UNAVAILABLE = "unavailable"
CREDIT_OFF = "off"
CREDIT_AVAILABLE = "available"
CREDIT_ACTIVE = "active"
CREDIT_EXHAUSTED = "exhausted"

# Every member of this set has an adapter that emits it. A
# state nothing produces is vocabulary, not a contract.
CREDIT_STATES = (
    CREDIT_UNAVAILABLE,
    CREDIT_OFF,
    CREDIT_AVAILABLE,
    CREDIT_ACTIVE,
    CREDIT_EXHAUSTED,
)

# States in which credit is actually being consumed. A
# provider that is merely eligible for credit is not engaged,
# and silence is not an admission either way.
CREDIT_ENGAGED = (CREDIT_ACTIVE, CREDIT_EXHAUSTED)

# Closed error vocabulary. A free text error routinely
# carries the URL it came from, and these URLs routinely
# carry an account identifier, so collectors return a code.
ERROR_NO_CREDENTIAL = "no_credential"
ERROR_CREDENTIAL_EXPIRED = "credential_expired"
ERROR_UNAUTHORIZED = "unauthorized"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_UNAVAILABLE = "endpoint_unavailable"
ERROR_MALFORMED = "malformed_response"
ERROR_BROWSER_UNAVAILABLE = "browser_unavailable"
ERROR_BROWSER_SESSION_MISSING = "browser_session_missing"
ERROR_COOLING_DOWN = "cooling_down"
ERROR_UNSUPPORTED = "unsupported_platform"
ERROR_NO_READING = "no_reading"

ERROR_CODES = (
    ERROR_NO_CREDENTIAL,
    ERROR_CREDENTIAL_EXPIRED,
    ERROR_UNAUTHORIZED,
    ERROR_RATE_LIMITED,
    ERROR_UNAVAILABLE,
    ERROR_MALFORMED,
    ERROR_BROWSER_UNAVAILABLE,
    ERROR_BROWSER_SESSION_MISSING,
    ERROR_COOLING_DOWN,
    ERROR_UNSUPPORTED,
    ERROR_NO_READING,
)


class ContractError(ValueError):
    """A value that does not satisfy the observation contract."""


def _finite_number(value: Any) -> bool:
    """Accept a real number, and reject bool, which is an int."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


@dataclass(frozen=True)
class Window:
    """One rolling limit and how much of it is spent.

    ``used_percent`` is percent consumed, never remaining.
    Providers disagree about which one they report, and the
    adapters convert, so nothing downstream has to ask.

    ``resets_in_seconds`` is a duration rather than an
    instant because providers report resets in at least three
    forms, and a duration is the only one a reader can act on
    without knowing the provider's clock.
    """

    label: str
    used_percent: float
    resets_in_seconds: float | None = None
    remaining: float | None = None
    limit: float | None = None

    def validate(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ContractError("window label must be a non-empty string")
        if not _finite_number(self.used_percent):
            raise ContractError("used_percent must be a finite number")
        if not 0.0 <= float(self.used_percent) <= 100.0:
            raise ContractError("used_percent must fall within 0 and 100")
        if self.resets_in_seconds is not None:
            if not _finite_number(self.resets_in_seconds):
                raise ContractError("resets_in_seconds must be a finite number")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        document: dict[str, Any] = {
            "label": self.label,
            "used_percent": round(float(self.used_percent), 4),
        }
        if self.resets_in_seconds is not None:
            document["resets_in_seconds"] = round(float(self.resets_in_seconds), 3)
        if self.remaining is not None:
            document["remaining"] = self.remaining
        if self.limit is not None:
            document["limit"] = self.limit
        return document


@dataclass(frozen=True)
class Credits:
    """Whether paid overage is engaged, and what was said."""

    state: str = CREDIT_UNAVAILABLE
    detail: str = ""

    def validate(self) -> None:
        if self.state not in CREDIT_STATES:
            raise ContractError("credit state outside the closed set: " + str(self.state))

    @property
    def engaged(self) -> bool:
        return self.state in CREDIT_ENGAGED

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"state": self.state, "detail": self.detail}


@dataclass(frozen=True)
class Observation:
    """Everything known about one provider at one moment."""

    provider: str
    collected_at: float
    windows: tuple[Window, ...] = ()
    credits: Credits = field(default_factory=Credits)
    plan: str = ""
    source: str = SOURCE_API
    freshness: str = FRESHNESS_LIVE
    error: str | None = None
    adapter_version: int = 1

    def validate(self) -> None:
        if not isinstance(self.provider, str) or not self.provider:
            raise ContractError("provider must be a non-empty string")
        if not _finite_number(self.collected_at):
            raise ContractError("collected_at must be a finite number")
        if self.source not in SOURCES:
            raise ContractError("source outside the closed set: " + str(self.source))
        if self.freshness not in FRESHNESS_STATES:
            raise ContractError("freshness outside the closed set")
        if self.error is not None and self.error not in ERROR_CODES:
            raise ContractError("error outside the closed vocabulary: " + str(self.error))
        if self.error is not None and self.windows:
            raise ContractError("a failed observation must not carry windows")
        for window in self.windows:
            window.validate()
        self.credits.validate()

    @property
    def answered(self) -> bool:
        """True when the provider actually reported a limit.

        An observation with no windows is unanswered even when
        it carries no error, because missing is never zero.
        """
        return self.error is None and bool(self.windows)

    def binding_window(self) -> Window | None:
        """The window closest to stopping work.

        The highest percentage binds. Ties break on the label
        so the choice is deterministic across runs, and pools
        of different durations are never averaged together.
        """
        if not self.windows:
            return None
        return sorted(
            self.windows,
            key=lambda window: (-float(window.used_percent), window.label),
        )[0]

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        binding = self.binding_window()
        document: dict[str, Any] = {
            "provider": self.provider,
            "collected_at": round(float(self.collected_at), 3),
            "source": self.source,
            "freshness": self.freshness,
            "plan": self.plan,
            "adapter_version": self.adapter_version,
            "windows": [window.to_dict() for window in self.windows],
            "credits": self.credits.to_dict(),
            "answered": self.answered,
        }
        if self.error is not None:
            document["error"] = self.error
        if binding is not None:
            document["binding_window"] = binding.to_dict()
        return document


def failed(provider: str, error: str, *, now: float | None = None, **extra: Any) -> Observation:
    """Build an unanswered observation carrying only a code."""
    if error not in ERROR_CODES:
        raise ContractError("error outside the closed vocabulary: " + str(error))
    return Observation(
        provider=provider,
        collected_at=time.time() if now is None else now,
        error=error,
        **extra,
    )


def snapshot(observations: list[Observation]) -> dict[str, Any]:
    """A whole-fleet document with the schema stamped on it."""
    ordered = sorted(observations, key=lambda item: item.provider)
    return {
        "schema": SCHEMA,
        "generated_at": round(time.time(), 3),
        "providers": [item.to_dict() for item in ordered],
        "answered": sum(1 for item in ordered if item.answered),
        "requested": len(ordered),
    }
