"""Accept a reading a browser took, without trusting it.

Every other source in this tool is something the process went
and fetched: it chose the endpoint, it held the credential, and
it knows what it asked for. This one is different. The number
arrives from somewhere else, computed by code running in a
browser the operator is signed in to, and the only thing that
makes it credible is a shared secret.

That difference is why this module is small and suspicious. It
takes a narrow document, rejects anything outside it, and
overwrites the three fields a caller could use to make a
reading look better than it is:

    source        forced, so an ingested number can never claim
                  it came from the provider's API
    collected_at  taken from this machine's clock, so a caller
                  cannot backdate a reading into a gap or
                  postdate one to outrank a fresher fetch
    freshness     derived here rather than asserted there

What remains is the measurement itself, which is the only part
a browser knows better than this process does.

The route exists because some providers put subscription usage
behind a session an API token cannot hold. Reading it needs a
signed in browser; the operator already has one; this is how it
hands over what it sees.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from typing import Any

from . import config, contract
from .providers import registry

# A reading is a handful of small numbers. Anything larger is
# not a reading, and refusing it early keeps a body that will
# never parse from being read into memory at all.
MAX_BODY_BYTES = 16 * 1024

# One provider may hand in a reading this often. The browser is
# driven by a person clicking, so this is not a rate limit in
# the usual sense; it stops a stuck loop or a held key from
# filling the store with duplicates.
MIN_SECONDS_BETWEEN = 5.0

# Same closed vocabulary the rest of the tool uses. A browser
# does not get to invent an error string.
INGESTIBLE_ERRORS = (
    contract.ERROR_NO_ALLOWANCE,
    contract.ERROR_BROWSER_SESSION_MISSING,
    contract.ERROR_UNAUTHORIZED,
)

TOKEN_BYTES = 32


class Refused(ValueError):
    """The document is not something this route will store.

    Carries a closed reason rather than a message, for the same
    reason adapters return closed error codes: the text of a
    parse failure tends to quote the thing that failed to
    parse.
    """

    def __init__(self, reason: str, status: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def create_token(**kwargs: Any) -> str:
    """Mint the shared secret and write it where only we can read.

    Returns the token so a caller can show it once. It is
    readable from the file afterwards by this user, which is
    the same trust boundary as every other file this tool
    writes.
    """
    path = config.ingest_token_path(**kwargs)
    config.ensure_private(path.parent)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    # Written through a temporary name so a reader never sees a
    # half written secret, and created at 0600 rather than
    # widened afterwards.
    temporary = path.with_suffix(".partial")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(token + "\n")
    os.replace(temporary, path)
    return token


def read_token(**kwargs: Any) -> str | None:
    """The configured secret, or None when the route is closed."""
    path = config.ingest_token_path(**kwargs)
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return token or None


def authorised(header: str | None, token: str | None) -> bool:
    """True when the request carries the configured secret.

    Compared with a constant time comparison, because a plain
    equality on a secret leaks its prefix to anyone willing to
    time the answer.
    """
    if not token or not header:
        return False
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    presented = header[len(prefix) :].strip()
    if not presented:
        return False
    return hmac.compare_digest(presented, token)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refused("malformed_" + field)
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise Refused("malformed_" + field)
    return number


def _optional_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    return _number(value, field)


def _window(item: Any) -> contract.Window:
    if not isinstance(item, dict):
        raise Refused("malformed_window")
    label = item.get("label")
    if not isinstance(label, str) or not label:
        raise Refused("malformed_window_label")
    scope = item.get("scope", contract.SCOPE_ACCOUNT)
    if scope not in contract.SCOPES:
        raise Refused("malformed_window_scope")
    window = contract.Window(
        label=label,
        used_percent=_number(item.get("used_percent"), "used_percent"),
        resets_in_seconds=_optional_number(item.get("resets_in_seconds"), "resets_in_seconds"),
        remaining=_optional_number(item.get("remaining"), "remaining"),
        limit=_optional_number(item.get("limit"), "limit"),
        scope=scope,
    )
    try:
        window.validate()
    except contract.ContractError:
        raise Refused("malformed_window") from None
    return window


def observation(document: Any, *, now: float | None = None) -> contract.Observation:
    """Turn a posted document into a reading, or refuse it.

    Refuses far more than it accepts. The provider must be one
    this tool knows, the windows must satisfy the same contract
    every adapter satisfies, and an unanswered reading must
    carry a code from the closed set rather than a sentence.
    """
    moment = time.time() if now is None else now
    if not isinstance(document, dict):
        raise Refused("malformed_document")

    provider = document.get("provider")
    if not isinstance(provider, str) or provider not in registry.PROVIDERS:
        raise Refused("unknown_provider", status=404)

    answered = document.get("answered")
    if not isinstance(answered, bool):
        raise Refused("malformed_answered")

    if not answered:
        code = document.get("error")
        if code not in INGESTIBLE_ERRORS:
            raise Refused("error_outside_the_closed_set")
        # Built here rather than copied, so the failure carries
        # this route's source and this machine's clock like an
        # answered reading does.
        failed = contract.failed(provider, code, now=moment)
        return contract.Observation(
            provider=failed.provider,
            collected_at=moment,
            windows=(),
            credits=failed.credits,
            plan="",
            source=contract.SOURCE_BROWSER_INGEST,
            freshness=contract.FRESHNESS_LIVE,
            error=code,
        )

    raw_windows = document.get("windows")
    if not isinstance(raw_windows, list) or not raw_windows:
        # Missing is never zero: an answered reading with no
        # window is not a provider at zero percent, it is a
        # document that failed to say anything.
        raise Refused("answered_without_a_window")
    if len(raw_windows) > 16:
        raise Refused("too_many_windows")
    windows = tuple(_window(item) for item in raw_windows)

    credits = document.get("credits")
    if credits is None:
        built = contract.Credits()
    elif isinstance(credits, dict):
        state = credits.get("state", "unavailable")
        detail = credits.get("detail", "")
        if state not in contract.CREDIT_STATES or not isinstance(detail, str):
            raise Refused("malformed_credits")
        built = contract.Credits(state, detail)
    else:
        raise Refused("malformed_credits")

    plan = document.get("plan", "")
    if not isinstance(plan, str) or len(plan) > 64:
        raise Refused("malformed_plan")

    reading = contract.Observation(
        provider=provider,
        # This machine's clock, never the caller's. A reading
        # that could name its own time could be dropped into a
        # gap in the history, or postdated to outrank a fetch
        # that actually happened later.
        collected_at=moment,
        windows=windows,
        credits=built,
        plan=plan,
        # Forced. A caller that asked for "api" would be
        # claiming a provenance no ingested number can have.
        source=contract.SOURCE_BROWSER_INGEST,
        freshness=contract.FRESHNESS_LIVE,
        error=None,
    )
    try:
        reading.validate()
    except contract.ContractError:
        raise Refused("malformed_document") from None
    return reading


def too_soon(connection: Any, provider: str, now: float, store: Any) -> bool:
    """True when this provider handed one in a moment ago."""
    document = store.latest(connection, provider)
    if not isinstance(document, dict):
        return False
    if document.get("source") != contract.SOURCE_BROWSER_INGEST:
        return False
    age = now - float(document.get("collected_at", 0.0))
    return 0.0 <= age < MIN_SECONDS_BETWEEN


def allowed_origins(environ: dict[str, str] | None = None) -> tuple[str, ...]:
    """Origins the browser may post from.

    Empty by default. A bookmarklet runs on the provider's own
    page, so the origin that posts is the provider's -- and
    naming them one at a time is the difference between a route
    the operator opened and a route any page can reach.
    """
    values = os.environ if environ is None else environ
    raw = values.get("AGENT_USAGE_INGEST_ORIGINS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def body_of(document: contract.Observation) -> bytes:
    return (json.dumps({"stored": document.provider}, sort_keys=True) + "\n").encode("utf-8")


def token_file_note(**kwargs: Any) -> str:
    """Where the secret lives, for a message that has to say."""
    return str(config.ingest_token_path(**kwargs))
