#!/usr/bin/env python3
"""Seed declared synthetic readings for the demo.

Every number here is invented. The point of the demo is the
behaviour around the numbers: that a provider which did not
answer is named rather than shown as zero, and that a
forecast which can be measured also says whether the window
resets before that pace would spend it.

The two Claude readings are two hours apart on purpose, so
the demo shows a measured rate rather than a declined one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_usage import config, contract, store  # noqa: E402

# Two readings two hours apart so a burn rate is measurable,
# one provider that answered once, and the rest that never did.
SEEDED = [
    ("claude", 1000.0, 20.0, 5400.0),
    ("claude", 8200.0, 40.0, 1800.0),
    ("codex", 8200.0, 12.5, 3600.0),
]
SILENT = ("grok", "kimi")


def seed(state: str) -> None:
    kwargs = {"environ": {config.STATE_ENV: state}}
    connection = store.connect(**kwargs)
    try:
        for provider, when, percent, resets in SEEDED:
            store.record(
                connection,
                contract.Observation(
                    provider=provider,
                    collected_at=when,
                    windows=(contract.Window("5-hour", percent, resets),),
                ),
            )
        for provider in SILENT:
            store.record(
                connection,
                contract.failed(provider, contract.ERROR_NO_CREDENTIAL, now=8200.0),
            )
    finally:
        connection.close()
    # Counted rather than spelled out, so removing a provider
    # cannot leave the transcript claiming the old total.
    print(
        "recorded %d synthetic readings, %d providers with no credential"
        % (len(SEEDED), len(SILENT))
    )


def redact_doctor() -> None:
    """Print the doctor document without this host's answers.

    Whether a credential happens to exist on the machine that
    rendered the demo is not a property of the tool.
    """
    document = json.load(sys.stdin)
    for entry in document.get("credentials", []):
        for field in ("present", "expired", "origin"):
            entry[field] = "<varies by machine>"
    document["state_dir"] = "<temporary>"
    document["browser_available"] = "<varies by machine>"
    json.dump(document, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed")
    parser.add_argument("--redact-doctor", action="store_true")
    arguments = parser.parse_args()
    if arguments.redact_doctor:
        redact_doctor()
        return 0
    if arguments.seed:
        seed(arguments.seed)
        return 0
    parser.error("choose --seed or --redact-doctor")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
