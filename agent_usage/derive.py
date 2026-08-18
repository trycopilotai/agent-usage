"""Burn rate and forecast, each free to decline.

Every function here may answer "not enough evidence". A
forecast invented from one sample is worse than no forecast,
because a reader acts on it. Declining is a first class
result and the API reports it as a status rather than as a
number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MINIMUM_SAMPLES = 2
# Below this the two samples are effectively simultaneous and
# the slope is dominated by measurement noise.
MINIMUM_SPAN_SECONDS = 60.0


def _since_last_reset(ordered: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop everything up to and including the last fall."""
    start = 0
    for index in range(1, len(ordered)):
        if ordered[index][1] < ordered[index - 1][1]:
            start = index
    return ordered[start:]


@dataclass(frozen=True)
class Estimate:
    """A number, or a plain reason there is not one."""

    value: float | None
    status: str

    @property
    def known(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        if self.value is None:
            return {"status": self.status}
        return {"status": self.status, "value": round(float(self.value), 6)}


UNKNOWN_FEW_SAMPLES = Estimate(None, "insufficient_samples")
UNKNOWN_SHORT_SPAN = Estimate(None, "span_too_short")
UNKNOWN_NOT_RISING = Estimate(None, "not_rising")
UNKNOWN_NO_WINDOW = Estimate(None, "no_binding_window")
# Distinct from not_rising. Nothing fell inside the live
# window; the window itself restarted, and too little has
# accumulated since to measure anything.
UNKNOWN_AFTER_RESET = Estimate(None, "window_reset")


def burn_rate_per_hour(samples: list[tuple[float, float]]) -> Estimate:
    """Percent consumed per hour since the last window reset.

    Samples are (timestamp, used_percent). A window that reset
    inside the span shows up as a fall from one reading to the
    next, and everything before that fall belongs to a window
    that no longer exists. Comparing only the first and last
    reading misses this: 80, then 10, then 90 is net rising,
    and reporting that slope would describe a window that was
    never consumed that way.
    """
    ordered = sorted((t, p) for t, p in samples if p is not None)
    usable = _since_last_reset(ordered)
    if len(usable) < MINIMUM_SAMPLES:
        if len(ordered) >= MINIMUM_SAMPLES:
            return UNKNOWN_AFTER_RESET
        return UNKNOWN_FEW_SAMPLES
    first_time, first_percent = usable[0]
    last_time, last_percent = usable[-1]
    span = last_time - first_time
    if span < MINIMUM_SPAN_SECONDS:
        return UNKNOWN_SHORT_SPAN
    delta = last_percent - first_percent
    if delta <= 0:
        return UNKNOWN_NOT_RISING
    return Estimate(delta / span * 3600.0, "measured")


def seconds_until_exhausted(used_percent: float, rate_per_hour: Estimate) -> Estimate:
    """How long until this window is spent, if it is rising."""
    if not rate_per_hour.known or rate_per_hour.value is None or rate_per_hour.value <= 0:
        return Estimate(None, rate_per_hour.status)
    remaining = max(0.0, 100.0 - float(used_percent))
    if remaining <= 0:
        # Not "exhausted". That word means paid overage being
        # consumed, and this is a window with nothing left,
        # which stops work rather than costing money.
        return Estimate(0.0, "window_spent")
    return Estimate(remaining / float(rate_per_hour.value) * 3600.0, "projected")


def forecast(observation: Any, samples: list[tuple[float, float]]) -> dict[str, Any]:
    """Burn and exhaustion for the window that binds."""
    binding = observation.binding_window() if observation is not None else None
    if binding is None:
        return {
            "status": UNKNOWN_NO_WINDOW.status,
            "burn_rate_per_hour": UNKNOWN_NO_WINDOW.to_dict(),
            "seconds_until_exhausted": UNKNOWN_NO_WINDOW.to_dict(),
        }
    rate = burn_rate_per_hour(samples)
    until = seconds_until_exhausted(binding.used_percent, rate)
    document = {
        # One field, describing the forecast rather than the
        # rate behind it. A measured rate still only yields a
        # projection, and calling that "measured" would tell a
        # reader an extrapolation was an observation.
        "status": until.status,
        "window": binding.label,
        "used_percent": round(float(binding.used_percent), 4),
        "burn_rate_per_hour": rate.to_dict(),
        "seconds_until_exhausted": until.to_dict(),
    }
    if binding.resets_in_seconds is not None:
        document["resets_in_seconds"] = round(float(binding.resets_in_seconds), 3)
        # A window that resets before it is spent will not be
        # spent, and saying so is the useful answer.
        if until.known and until.value is not None:
            document["resets_before_exhausted"] = float(binding.resets_in_seconds) < float(
                until.value
            )
    return document
