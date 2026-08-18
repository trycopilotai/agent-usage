"""A Markdown block an agent or a person can read.

It states what was asked, what answered, and what did not.
A provider that failed is listed with its code rather than
omitted, because a report that silently drops a provider
reads as a report that the provider is fine.
"""

from __future__ import annotations

from typing import Any

from . import contract

HEADING = "## Provider usage"


def _duration(seconds: Any) -> str:
    if seconds is None:
        return "unknown"
    value = float(seconds)
    if value <= 0:
        return "now"
    hours, remainder = divmod(int(value), 3600)
    minutes = remainder // 60
    if hours >= 24:
        days, leftover = divmod(hours, 24)
        return str(days) + "d " + str(leftover) + "h"
    if hours:
        return str(hours) + "h " + str(minutes) + "m"
    return str(minutes) + "m"


def render(observations: list[contract.Observation], source_label: str = "agent-usage") -> str:
    lines = [HEADING, ""]
    answered = [item for item in observations if item.answered]
    unanswered = [item for item in observations if not item.answered]
    if answered:
        lines.append("| Provider | Window | Used | Resets in | Credits |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in sorted(answered, key=lambda entry: entry.provider):
            binding = item.binding_window()
            lines.append(
                "| "
                + " | ".join(
                    [
                        item.provider,
                        binding.label,
                        format(float(binding.used_percent), ".1f") + "%",
                        _duration(binding.resets_in_seconds),
                        item.credits.state,
                    ]
                )
                + " |"
            )
        lines.append("")
    for item in sorted(unanswered, key=lambda entry: entry.provider):
        lines.append("- " + item.provider + ": no answer (" + str(item.error) + ")")
    if unanswered:
        lines.append("")
    lines.append(
        "Read by "
        + source_label
        + ". "
        + str(len(answered))
        + " of "
        + str(len(observations))
        + " providers answered."
    )
    return "\n".join(lines).rstrip() + "\n"
