#!/usr/bin/env python3
"""Launcher so the skill can be invoked from any directory.

It puts the repository root on the path and hands off to the
same CLI a person runs, so the agent path and the human path
cannot diverge.
"""

from __future__ import annotations

import os
import sys

# realpath, not abspath: this file is also reachable through
# the repository's "skill" symlink, which sits one directory
# shallower, and walking up from there overshoots the root.
HERE = os.path.realpath(__file__)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent_usage.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
