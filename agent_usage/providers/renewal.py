"""Renew an expired Claude OAuth credential, and store it.

`credentials.py` promises that nothing in it writes,
refreshes, or transmits a credential. That promise is worth
keeping, so renewal lives here instead of being smuggled into
the finder.

Two facts about this provider shape everything below.

The refresh token is **rotated on every use**. The response
carries a new one, and the token that bought it stops working
the moment it is spent. So a renewal that succeeds without
storing its result does not leave the account as it found it,
it locks the account out. This module therefore refuses to
renew unless it has somewhere to write the answer, and it
writes before it reports success.

And the token endpoint sits behind a filter that rejects the
default Python user agent outright, with a 403 that has
nothing to do with the credential. A request from here states
what it is, which is both honest and the difference between
renewing and being turned away at the door.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# The current endpoint first, then the one older clients still
# carry, because an account may be issued either.
TOKEN_URLS = (
    "https://platform.claude.com/v1/oauth/token",
    "https://console.anthropic.com/v1/oauth/token",
)

# The public client id of the first party CLI. It identifies
# the application, not the operator, and is not a secret.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

USER_AGENT = "agent-usage (+https://github.com/trycopilotai/agent-usage)"
RENEWAL_TIMEOUT_SECONDS = 20

CREDENTIALS_RELATIVE = (".claude", ".credentials.json")
OAUTH_KEY = "claudeAiOauth"

# The mode the client writes, and the mode this module
# restores. A renewed credential must not be left more
# readable than the one it replaced.
CREDENTIAL_MODE = 0o600


def credentials_path(home: Path | None = None) -> Path:
    root = Path.home() if home is None else Path(home)
    return root.joinpath(*CREDENTIALS_RELATIVE)


def _read(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _post(url: str, payload: dict[str, Any], opener: Any) -> Any:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with opener(request, timeout=RENEWAL_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _write(path: Path, document: Any) -> None:
    """Replace the credential file atomically, at its own mode.

    The temporary file is created beside the target so the
    replace cannot cross a filesystem boundary and degrade
    into a copy, which would leave a window where the file is
    half written.
    """
    temporary = path.with_name(path.name + ".renewing")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(document, handle)
    os.chmod(temporary, CREDENTIAL_MODE)
    os.replace(temporary, path)


def renew_claude(
    home: Path | None = None,
    opener: Any = None,
    now: float | None = None,
) -> bool:
    """Spend the refresh token and store what comes back.

    Returns whether the stored credential was replaced. Every
    failure returns False and leaves the file exactly as it
    was, because a partially renewed credential is worse than
    an expired one: the expired one can still be renewed.
    """
    moment = time.time() if now is None else now
    send = urllib.request.urlopen if opener is None else opener
    path = credentials_path(home)

    document = _read(path)
    if not isinstance(document, dict):
        return False
    oauth = document.get(OAUTH_KEY)
    if not isinstance(oauth, dict):
        return False
    refresh = oauth.get("refreshToken")
    if not isinstance(refresh, str) or not refresh:
        return False

    # A refresh token that has itself expired cannot buy
    # anything, and asking spends a request to be told so.
    expires = oauth.get("refreshTokenExpiresAt")
    if isinstance(expires, (int, float)) and not isinstance(expires, bool):
        if float(expires) / 1000.0 < moment:
            return False

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": CLIENT_ID,
    }
    answer: Any = None
    for url in TOKEN_URLS:
        try:
            answer = _post(url, payload, send)
            break
        except (urllib.error.URLError, OSError, ValueError):
            # Deliberately not reported upward. The string form
            # of these errors carries the URL and the payload.
            answer = None
    if not isinstance(answer, dict):
        return False

    access = answer.get("access_token")
    if not isinstance(access, str) or not access:
        return False

    renewed = dict(oauth)
    renewed["accessToken"] = access
    # The rotated token, or the account is locked out the next
    # time this runs.
    rotated = answer.get("refresh_token")
    if isinstance(rotated, str) and rotated:
        renewed["refreshToken"] = rotated
    lifetime = answer.get("expires_in")
    if isinstance(lifetime, (int, float)) and not isinstance(lifetime, bool):
        renewed["expiresAt"] = int((moment + float(lifetime)) * 1000)
    refresh_lifetime = answer.get("refresh_token_expires_in")
    if isinstance(refresh_lifetime, (int, float)) and not isinstance(refresh_lifetime, bool):
        renewed["refreshTokenExpiresAt"] = int((moment + float(refresh_lifetime)) * 1000)

    stored = dict(document)
    stored[OAUTH_KEY] = renewed
    try:
        _write(path, stored)
    except OSError:
        # Nothing was replaced, so the old refresh token is
        # already spent and the next attempt will fail. Say so
        # by reporting failure rather than a false success.
        return False
    return True
