#!/usr/bin/env python3
"""Re-check every hash the demo manifest records.

The manifest claims the transcript was produced by specific
source bytes at a specific commit and was not edited
afterwards. This proves those claims or fails.

Source digests are read out of the tree at ``input_commit``,
not out of the working tree. An ancestry check alone lets the
recorded commit and the recorded bytes disagree while every
test stays green, which is exactly the drift this file exists
to catch.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "evidence" / "demo-manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def failures() -> list[str]:
    problems: list[str] = []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    output = ROOT / manifest["output_path"]
    if digest(output) != manifest["output_sha256"]:
        problems.append("transcript bytes differ from the recorded digest")

    commit = manifest["input_commit"]
    result = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
    )
    if result.returncode != 0:
        problems.append("input commit is not an ancestor of HEAD: " + commit)
        return problems

    recorded_sources = dict(manifest["source_sha256"])
    recorded_sources[manifest["protocol_path"]] = manifest["protocol_sha256"]
    for relative, recorded in sorted(recorded_sources.items()):
        blob = subprocess.run(
            ["git", "-C", str(ROOT), "show", commit + ":" + relative],
            capture_output=True,
        )
        if blob.returncode != 0:
            problems.append("recorded source is absent at the input commit: " + relative)
            continue
        if hashlib.sha256(blob.stdout).hexdigest() != recorded:
            problems.append("recorded source does not match the input commit: " + relative)
        path = ROOT / relative
        if not path.is_file():
            problems.append("recorded source is missing from the tree: " + relative)
            continue
        if digest(path) != recorded:
            # Both halves are needed. The commit check catches a
            # manifest pointing at the wrong tree; this catches a
            # source edited after the transcript was made.
            problems.append("source changed since the transcript was made: " + relative)

    if manifest.get("transcript_edited") is not False:
        problems.append("transcript is not declared unedited")
    return problems


def main() -> int:
    problems = failures()
    for problem in problems:
        sys.stderr.write(problem + "\n")
    if problems:
        return 1
    sys.stdout.write("demo evidence verified\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
