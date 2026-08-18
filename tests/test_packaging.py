"""The release surface, asserted rather than assumed.

These are the checks a reviewer would otherwise have to make
by eye, and the ones a rename or a version bump quietly
breaks.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "agent-usage"
SKILL_DIR = ROOT / "skills" / NAME
SKILL_FILE = SKILL_DIR / "SKILL.md"

PRIVATE_INFIXES = (".gpt.", ".claude.", ".codex.")


def _tracked_files():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [name for name in result.stdout.decode().split("\0") if name]


def _frontmatter():
    text = SKILL_FILE.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 3)
    return text[4:end], text[end + 5 :]


def test_frontmatter_carries_name_and_description_only():
    raw, _ = _frontmatter()
    keys = re.findall(r"^([a-z_]+):", raw, flags=re.MULTILINE)
    assert keys == ["name", "description"]


def test_name_matches_the_directory_and_is_kebab_case():
    raw, _ = _frontmatter()
    name = re.search(r"^name:\s*(\S+)", raw, flags=re.MULTILINE).group(1)
    assert name == NAME == SKILL_DIR.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
    assert len(name) <= 64


def test_description_says_when_to_use_it_and_fits_the_limit():
    raw, _ = _frontmatter()
    block = raw.split("description:", 1)[1]
    description = " ".join(line.strip() for line in block.strip().splitlines())
    assert 0 < len(description) <= 1024
    assert "Use when" in description


def test_the_skill_body_stays_under_the_length_guideline():
    assert len(SKILL_FILE.read_text(encoding="utf-8").splitlines()) < 500


def test_the_skill_symlink_points_into_the_regular_directory():
    link = ROOT / "skill"
    assert link.is_symlink()
    # Never reversed: the tracked regular directory is the
    # canonical package and the symlink points at it.
    assert os.readlink(link) == "skills/" + NAME
    assert (link / "SKILL.md").exists()
    assert not SKILL_DIR.is_symlink()


def test_both_product_manifests_agree():
    claude = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    codex = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    for manifest in (claude, codex):
        assert manifest["name"] == NAME
        assert manifest["skills"] == "./skills/"
        assert manifest["license"] == "MIT"
    assert claude["version"] == codex["version"]
    # The Codex manifest adds an interface block and nothing
    # that contradicts the Claude one.
    assert "interface" in codex
    assert "interface" not in claude


def test_the_codex_agent_file_offers_the_dollar_invocation():
    text = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "$" + NAME in text


def test_the_readme_documents_both_products_and_every_invocation():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "### Claude Code" in text
    assert "### Codex" in text
    for form in ("/" + NAME, "/" + NAME + ":" + NAME, "$" + NAME, "@" + NAME):
        assert form in text


def test_no_tracked_path_carries_a_private_provenance_infix():
    for name in _tracked_files():
        for component in name.split("/"):
            for infix in PRIVATE_INFIXES:
                assert infix not in component.lower(), name


def test_the_license_is_mit_and_names_the_organisation():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Try Copilot AI" in text


def test_the_version_is_stated_once_and_agrees_everywhere():
    claude = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    import agent_usage

    assert claude["version"] == agent_usage.__version__


def test_the_social_preview_is_the_size_github_expects():
    import struct

    png = (ROOT / "assets" / "social-preview.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (1280, 640)


def test_the_social_preview_svg_matches_its_generator():
    """The committed art is rebuildable, not hand edited."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_social_preview.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
