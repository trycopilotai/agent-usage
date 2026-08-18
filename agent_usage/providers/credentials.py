"""Find provider credentials without ever reporting them.

Each supported client already stores its own credential in
its own place. This module locates one and hands it to an
adapter. It reports only shape, meaning present, absent, or
expired, because a diagnostic that prints a token in order to
say a token exists has recreated the problem it reports.

Nothing here writes, refreshes, or transmits a credential.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Reading the macOS keychain shells out to the system binary.
# An absolute path is used so a shadowed name on PATH cannot
# be asked for the operator's credentials.
SECURITY_BIN = "/usr/bin/security"
KEYCHAIN_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Credential:
    """A located credential, plus what may be said about it."""

    provider: str
    present: bool
    expired: bool = False
    token: str | None = None
    account: str | None = None
    origin: str = ""

    def describe(self) -> dict[str, Any]:
        """Shape only. The token never appears in this dict."""
        return {
            "provider": self.provider,
            "present": self.present,
            "expired": self.expired,
            "origin": self.origin,
        }


def _home(home: Path | None = None) -> Path:
    return Path.home() if home is None else Path(home)


def _read_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _keychain_secret(service: str, runner: Any = None) -> str:
    """Read one generic password, or return an empty string."""
    if runner is None:
        runner = subprocess.run
    if not os.path.exists(SECURITY_BIN):
        return ""
    try:
        finished = runner(
            [SECURITY_BIN, "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if getattr(finished, "returncode", 1) != 0:
        return ""
    return (finished.stdout or "").strip()


def _nested(document: Any, *keys: str) -> Any:
    current = document
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def claude(
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    runner: Any = None,
) -> Credential:
    """Keychain first, then the file the Linux client writes."""
    raw = _keychain_secret("Claude Code-credentials", runner=runner)
    origin = "keychain"
    document: Any = None
    if raw:
        try:
            document = json.loads(raw)
        except ValueError:
            document = None
    if document is None:
        origin = "file"
        document = _read_json(_home(home) / ".claude" / ".credentials.json")
    token = _nested(document, "claudeAiOauth", "accessToken")
    if not isinstance(token, str) or not token:
        return Credential("claude", present=False)
    expires = _nested(document, "claudeAiOauth", "expiresAt")
    expired = False
    if isinstance(expires, (int, float)) and not isinstance(expires, bool):
        # This client records milliseconds since the epoch.
        expired = float(expires) / 1000.0 < time.time()
    return Credential("claude", present=True, expired=expired, token=token, origin=origin)


def codex(
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    runner: Any = None,
) -> Credential:
    """Bearer plus the account id the usage route requires."""
    document = _read_json(_home(home) / ".codex" / "auth.json")
    token = _nested(document, "tokens", "access_token")
    if not isinstance(token, str) or not token:
        return Credential("codex", present=False)
    account = _nested(document, "tokens", "account_id")
    return Credential(
        "codex",
        present=True,
        token=token,
        account=account if isinstance(account, str) else None,
        origin="file",
    )


def kimi(
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    runner: Any = None,
) -> Credential:
    """OAuth file first, then the API key install.

    An API key install writes no credentials file at all, so
    a missing file is not the same as a missing credential.
    """
    root = _home(home)
    document = _read_json(root / ".kimi-code" / "credentials" / "kimi-code.json")
    token = _nested(document, "access_token")
    if isinstance(token, str) and token:
        expires = _nested(document, "expires_at")
        expired = False
        if isinstance(expires, (int, float)) and not isinstance(expires, bool):
            expired = float(expires) < time.time()
        return Credential("kimi", present=True, expired=expired, token=token, origin="file")
    config = root / ".kimi-code" / "config.toml"
    key = _kimi_config_key(config)
    if key:
        return Credential("kimi", present=True, token=key, origin="config")
    return Credential("kimi", present=False)


def _kimi_config_key(path: Path) -> str:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        return ""
    try:
        with open(path, "rb") as handle:
            document = tomllib.load(handle)
    except (OSError, ValueError):
        return ""
    providers = document.get("providers")
    if not isinstance(providers, dict):
        return ""
    for name, entry in providers.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "kimi":
            continue
        if not str(name).startswith("managed:"):
            continue
        key = entry.get("api_key")
        if isinstance(key, str) and key:
            return key
    return ""


def zai(
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    runner: Any = None,
) -> Credential:
    """The agent auth file, then the documented variable."""
    document = _read_json(_home(home) / ".pi" / "agent" / "auth.json")
    entry = _nested(document, "zai")
    if isinstance(entry, dict):
        key = entry.get("key")
        if isinstance(key, str) and key:
            return Credential("zai", present=True, token=key, origin="file")
    values = os.environ if environ is None else environ
    key = values.get("ZAI_API_KEY")
    if isinstance(key, str) and key:
        return Credential("zai", present=True, token=key, origin="environment")
    return Credential("zai", present=False)


def grok(
    home: Path | None = None,
    environ: dict[str, str] | None = None,
    runner: Any = None,
) -> Credential:
    """The first keyed entry in the client's auth file.

    The file's top level key names the account and is not
    stable, so the entry is found by shape rather than name.
    """
    document = _read_json(_home(home) / ".grok" / "auth.json")
    if not isinstance(document, dict):
        return Credential("grok", present=False)
    for entry in document.values():
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if isinstance(key, str) and key:
            return Credential("grok", present=True, token=key, origin="file")
    return Credential("grok", present=False)


# Every finder takes the same three arguments and ignores the
# ones it has no use for, so describe_all can hand the same
# call to all of them. A finder with a narrower signature
# makes that loop raise for one provider and not the others.
DISCOVERY = {
    "claude": claude,
    "codex": codex,
    "kimi": kimi,
    "zai": zai,
    "grok": grok,
}


def discover(provider: str, **kwargs: Any) -> Credential:
    finder = DISCOVERY.get(provider)
    if finder is None:
        return Credential(provider, present=False)
    return finder(**kwargs)


def describe_all(**kwargs: Any) -> list[dict[str, Any]]:
    """Shape of every credential, for the doctor command."""
    return [discover(name, **kwargs).describe() for name in sorted(DISCOVERY)]
