"""Where this tool keeps state, and how to move it.

Every path is derived from one root, and that root is
configurable. Nothing here is hardcoded to a user, a machine,
or an installation, so two checkouts on one host can run
against separate state without colliding.

Resolution order, highest first:

1. the ``AGENT_USAGE_STATE_DIR`` environment variable;
2. ``$XDG_STATE_HOME/agent-usage``;
3. ``~/.local/state/agent-usage``.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "agent-usage"
STATE_ENV = "AGENT_USAGE_STATE_DIR"
XDG_ENV = "XDG_STATE_HOME"


def state_dir(environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    values = os.environ if environ is None else environ
    explicit = values.get(STATE_ENV)
    if isinstance(explicit, str) and explicit:
        return Path(explicit)
    xdg = values.get(XDG_ENV)
    if isinstance(xdg, str) and xdg:
        return Path(xdg) / APP_NAME
    root = Path.home() if home is None else Path(home)
    return root / ".local" / "state" / APP_NAME


def database_path(**kwargs) -> Path:
    return state_dir(**kwargs) / "usage.sqlite3"


def browser_profile_dir(provider: str, **kwargs) -> Path:
    return state_dir(**kwargs) / "browser" / provider


def screenshot_path(provider: str, **kwargs) -> Path:
    """One file per provider, overwritten on each capture.

    Only the latest is kept. A history of screenshots of a
    logged in account page is a liability rather than a
    feature, and nothing in this tool reads an older one.
    """
    return state_dir(**kwargs) / "screenshots" / (provider + ".png")


def cooldown_path(**kwargs) -> Path:
    return state_dir(**kwargs) / "browser" / "cooldown.json"


def ingest_token_path(**kwargs) -> Path:
    """The shared secret a browser presents to hand in a reading.

    Absent by default, and its absence is what keeps the
    ingest route closed. Creating this file is the whole act
    of enabling it, so a deployment that never wanted the
    route does not have to remember to turn it off.
    """
    return state_dir(**kwargs) / "ingest-token"


def ensure_private(path: Path) -> Path:
    """Create a directory only this user can read."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path
