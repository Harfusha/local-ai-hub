"""Companion agent skills are installed idempotently without overwriting edits."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import setup


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPANIONS = tuple(setup.COMPANION_SKILLS)


@pytest.mark.parametrize("name", COMPANIONS)
def test_companion_skill_frontmatter_and_declaration(name):
    source = REPO_ROOT / "skills" / name / "SKILL.md"
    assert source.is_file(), f"missing setup companion: {name}"
    content = source.read_text(encoding="utf-8")
    assert content.startswith("---\n"), name
    assert "\n---\n" in content[4:], name
    assert f"name: {name}" in content.split("\n---\n", 1)[0], name


def test_idempotent_companion_install_retains_modified_owned_skill(tmp_path):
    install_dir = tmp_path / "install"
    skills = install_dir / "skills"
    for name in ("local-ai-orchestrator", *COMPANIONS):
        target = skills / name
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(f"---\nname: {name}\n---\nfixture\n", encoding="utf-8")
    target = tmp_path / "home" / ".agents" / "skills"
    setup.install_agent_skills(install_dir, target)
    manifest = install_dir / ".local-ai-hub-skill-ownership.json"
    assert manifest.is_file()
    baseline = (target / "local-ai-orchestrator" / "SKILL.md").read_bytes()
    setup.install_agent_skills(install_dir, target)
    assert (target / "local-ai-orchestrator" / "SKILL.md").read_bytes() == baseline
    for name in COMPANIONS:
        assert (target / name / "SKILL.md").is_file()
    # A user-authored modification must survive the next managed update.
    modified = target / "ponytail" / "USER_NOTES.md"
    modified.write_text("user content remains\n", encoding="utf-8")
    (skills / "ponytail" / "SKILL.md").write_text("---\nname: ponytail\n---\nnew version\n", encoding="utf-8")
    setup.install_agent_skills(install_dir, target)
    assert modified.read_text(encoding="utf-8") == "user content remains\n"
    assert (target / "ponytail" / "SKILL.md").read_text(encoding="utf-8").endswith("fixture\n")
    assert isinstance(json.loads(manifest.read_text(encoding="utf-8")).get("skills"), dict)


def test_mcp_only_skill_setup_can_skip_companions(tmp_path):
    install_dir = tmp_path / "install"
    source = install_dir / "skills" / "local-ai-orchestrator"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: local-ai-orchestrator\n---\nfixture\n", encoding="utf-8")
    target = tmp_path / "host" / "skills"
    setup.install_agent_skills(install_dir, target, include_companion=False)
    assert (target / "local-ai-orchestrator" / "SKILL.md").is_file()
    assert not (target / "ponytail").exists()
