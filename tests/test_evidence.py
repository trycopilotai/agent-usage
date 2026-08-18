"""Prove the evidence verifier rejects what it claims to.

A test that reads a value out of the transcript and asserts
it appears in the transcript proves nothing. These build a
tampered copy of the repository and require the verifier to
fail on each way the evidence can become untrue.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IGNORED = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".pytest_cache")


def _copy() -> Path:
    destination = Path(tempfile.mkdtemp()) / "repo"
    shutil.copytree(ROOT, destination, ignore=IGNORED, symlinks=True)
    return destination


def _verify(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "verify_demo.py")],
        capture_output=True,
        text=True,
    )


def test_the_evidence_verifies_as_shipped():
    assert _verify(ROOT).returncode == 0


def test_editing_the_transcript_is_caught():
    root = _copy()
    transcript = root / "evidence" / "transcripts" / "demo-session.txt"
    transcript.write_text(transcript.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    result = _verify(root)
    assert result.returncode == 1
    assert "transcript bytes differ" in result.stderr


def test_changing_a_recorded_source_is_caught():
    root = _copy()
    source = root / "agent_usage" / "report.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
    result = _verify(root)
    assert result.returncode == 1
    assert "source changed since the transcript was made" in result.stderr


def test_a_removed_source_is_caught():
    root = _copy()
    (root / "scripts" / "seed_demo.py").unlink()
    result = _verify(root)
    assert result.returncode == 1
    assert "recorded source is missing" in result.stderr


def test_claiming_an_edited_transcript_is_unedited_is_caught():
    root = _copy()
    path = root / "evidence" / "demo-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["transcript_edited"] = True
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = _verify(root)
    assert result.returncode == 1
    assert "not declared unedited" in result.stderr


def test_an_unreachable_input_commit_is_caught():
    root = _copy()
    path = root / "evidence" / "demo-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["input_commit"] = "0" * 40
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = _verify(root)
    assert result.returncode == 1
    assert "not an ancestor" in result.stderr


def test_the_transcript_declares_its_readings_synthetic():
    manifest = json.loads((ROOT / "evidence" / "demo-manifest.json").read_text(encoding="utf-8"))
    # The claim the README makes about the demo has to be a
    # property of the manifest, not a sentence in prose.
    assert manifest["readings"] == "synthetic"


def test_a_manifest_pointing_at_the_wrong_commit_is_caught():
    """Ancestry alone let the commit and the bytes disagree."""
    root = _copy()
    path = root / "evidence" / "demo-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    parent = subprocess.run(
        ["git", "-C", str(root), "rev-parse", manifest["input_commit"] + "^"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest["input_commit"] = parent
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = _verify(root)
    assert result.returncode == 1
    assert "does not match the input commit" in result.stderr


def test_the_protocol_digest_is_verified_too():
    root = _copy()
    protocol = root / "skills" / "agent-usage" / "SKILL.md"
    protocol.write_text(protocol.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    result = _verify(root)
    assert result.returncode == 1
    assert "SKILL.md" in result.stderr


def test_the_readme_states_the_number_of_tamper_tests_correctly():
    """A count in prose drifts. Pin it to the actual count.

    This number has been wrong twice. Counting the tests that
    require the verifier to fail, rather than trusting the
    sentence, makes the sentence maintain itself.
    """
    import re

    # Assembled rather than written out, so this test's own
    # source does not contain the phrase it counts.
    needle = "assert result." + "returncode == 1"
    source = Path(__file__).read_text(encoding="utf-8")
    bodies = source.split("\ndef ")
    tampering = [body for body in bodies if needle in body]

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    match = re.search(r"tampers with a copy\s+(\w+)\s+ways", readme.replace("\n", " "))
    assert match is not None, "README no longer states a tamper count"
    assert words[match.group(1)] == len(tampering), "README says %s, the file has %d" % (
        match.group(1),
        len(tampering),
    )
