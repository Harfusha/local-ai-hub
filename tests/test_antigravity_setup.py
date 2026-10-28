from pathlib import Path
import importlib.util
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hub_setup_antigravity_test", ROOT / "tools" / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def test_antigravity_policy_preserves_unmanaged_text_and_is_idempotent(tmp_path):
    rules = tmp_path / "GEMINI.md"
    rules.write_bytes(b"My custom rules.\r\nSecond rule.\n")
    setup.merge_antigravity_skill_policy(rules, False)
    first = rules.read_text(encoding="utf-8")
    setup.merge_antigravity_skill_policy(rules, False)
    assert rules.read_text(encoding="utf-8") == first
    assert "My custom rules." in first
    assert b"My custom rules.\r\nSecond rule.\n" in rules.read_bytes()
    assert "using-superpowers/SKILL.md" in first
    assert "caveman/SKILL.md" in first
    assert "local-ai-orchestrator/SKILL.md" in first
    assert "ultra" in first.lower()
    assert "normal mode" in first and "stop caveman" in first


def test_antigravity_policy_is_prepended_and_targets_discoverable_skills(tmp_path):
    rules = tmp_path / "AGENTS.md"
    rules.write_text("Keep my existing instructions.\n", encoding="utf-8")

    setup.merge_antigravity_skill_policy(rules, False)
    text = rules.read_text(encoding="utf-8")

    assert text.startswith(setup.ANTIGRAVITY_POLICY_BEGIN)
    assert text.index(setup.ANTIGRAVITY_POLICY_END) < text.index("Keep my existing instructions.")
    assert "~/.gemini/skills/using-superpowers/SKILL.md" in text
    assert "~/.gemini/skills/caveman/SKILL.md" in text
    assert "~/.gemini/config/skills/" not in text
    assert "ultra mode" in text


def test_superpowers_install_preserves_custom_skill_and_uses_pinned_archive(tmp_path, monkeypatch):
    import io
    import zipfile
    import hashlib

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("repo/skills/using-superpowers/SKILL.md", "bootstrap")
        archive.writestr("repo/skills/brainstorming/SKILL.md", "upstream")
    payload = data.getvalue()
    monkeypatch.setattr(setup, "SUPERPOWERS_ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(setup, "download_superpowers_archive", lambda: payload)
    target = tmp_path / "skills"
    custom = target / "brainstorming" / "SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_text("mine", encoding="utf-8")
    setup.install_superpowers_skills(target)
    assert custom.read_text(encoding="utf-8") == "mine"
    assert (target / "using-superpowers" / "SKILL.md").read_text(encoding="utf-8") == "bootstrap"
    setup.install_superpowers_skills(target)
    assert custom.read_text(encoding="utf-8") == "mine"
    cached = tmp_path / ".local-ai-hub-superpowers" / "skills" / "using-superpowers" / "SKILL.md"
    cached.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from pinned archive"):
        setup.install_superpowers_skills(target)
    assert (target / "using-superpowers" / "SKILL.md").read_text(encoding="utf-8") == "bootstrap"


def test_superpowers_rejects_wrong_checksum_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "download_superpowers_archive", lambda: b"invalid")
    target = tmp_path / "skills"
    with pytest.raises(ValueError, match="checksum mismatch"):
        setup.install_superpowers_skills(target)
    assert not target.exists()


def test_gemini_setup_reports_superpowers_download_or_integrity_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup, "install_agent_skills", lambda *a, **k: None)
    monkeypatch.setattr(setup, "install_superpowers_skills", lambda *a, **k: (_ for _ in ()).throw(ValueError("checksum mismatch")))
    with pytest.raises(RuntimeError, match="Antigravity Superpowers installation failed: checksum mismatch"):
        setup.configure_gemini_instance(tmp_path / ".gemini", tmp_path / "install", Path("python"), None,
                                        {}, False, True, project_root=tmp_path / "project")
    assert "ERROR: Antigravity Superpowers installation failed: checksum mismatch" in capsys.readouterr().out


def test_superpowers_download_has_overall_deadline(monkeypatch):
    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read1(self, size):
            return b"data"

    clock = iter([0.0, 1.0, 31.0])
    monkeypatch.setattr(setup, "monotonic", lambda: next(clock))
    monkeypatch.setattr(setup.urllib.request, "urlopen", lambda *args, **kwargs: SlowResponse())
    with pytest.raises(TimeoutError, match="deadline"):
        setup.download_superpowers_archive()


def test_superpowers_rejects_traversal_before_installing(tmp_path, monkeypatch):
    import io
    import zipfile
    import hashlib

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("repo/skills/using-superpowers/SKILL.md", "bootstrap")
        archive.writestr("repo/skills/../outside/SKILL.md", "escape")
    payload = data.getvalue()
    monkeypatch.setattr(setup, "SUPERPOWERS_ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(setup, "download_superpowers_archive", lambda: payload)
    with pytest.raises(ValueError, match="Unsafe"):
        setup.install_superpowers_skills(tmp_path / "skills")
    assert not (tmp_path / "outside").exists()


def test_gemini_setup_enables_global_policy_and_preserves_existing_rules(tmp_path, monkeypatch):
    gemini = tmp_path / ".gemini"
    gemini.mkdir()
    rules = gemini / "GEMINI.md"
    rules.write_text("Existing user rules.\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(setup, "install_agent_skills", lambda install, target, **kw: calls.append(target))
    monkeypatch.setattr(setup, "install_superpowers_skills", lambda target, manifest: calls.append(target))
    monkeypatch.setattr(setup, "merge_global_policy", lambda *a, **k: None)
    monkeypatch.setattr(setup, "merge_token_economy_policy", lambda *a, **k: None)
    monkeypatch.setattr(setup, "json_mcp_merge", lambda *a, **k: None)
    monkeypatch.setattr(setup, "sync_antigravity_mcp_config", lambda *a, **k: None)
    monkeypatch.setattr(setup, "sync_antigravity_config_json", lambda *a, **k: None)
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *a, **k: {})
    setup.configure_gemini_instance(gemini, tmp_path / "install", Path("python"), None, {}, False, True,
                                    project_root=tmp_path / "project")
    assert gemini / "skills" in calls
    assert "Existing user rules." in rules.read_text(encoding="utf-8")
    active = (gemini / "AGENTS.md").read_text(encoding="utf-8")
    assert active.startswith(setup.ANTIGRAVITY_POLICY_BEGIN)
    assert "using-superpowers/SKILL.md" in active and "caveman/SKILL.md" in active
    assert (tmp_path / "project" / "AGENTS.md").is_file()
    assert (tmp_path / "project" / "AGENTS.md").read_text(encoding="utf-8").startswith(setup.ANTIGRAVITY_POLICY_BEGIN)


def test_project_and_global_rules_are_idempotent_and_preserve_unmanaged_skills(tmp_path, monkeypatch):
    gemini = tmp_path / ".gemini"
    project = tmp_path / "project"
    gemini.mkdir()
    project.mkdir()
    (gemini / "AGENTS.md").write_bytes(b"Global user rule.\r\n")
    (project / "AGENTS.md").write_text("Project user rule.\n", encoding="utf-8")
    unmanaged = gemini / "skills" / "my-custom-skill" / "SKILL.md"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_text("User skill", encoding="utf-8")
    for name in ("install_agent_skills", "install_superpowers_skills", "merge_global_policy",
                 "merge_token_economy_policy", "json_mcp_merge", "sync_antigravity_mcp_config",
                 "sync_antigravity_config_json"):
        monkeypatch.setattr(setup, name, lambda *a, **k: None)
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *a, **k: {})

    for _ in range(2):
        setup.configure_gemini_instance(gemini, tmp_path / "install", Path("python"), None, {}, False, True,
                                         project_root=project)

    global_rules = (gemini / "AGENTS.md").read_bytes()
    project_rules = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert global_rules.startswith(b"<!-- BEGIN LOCAL AI HUB ANTIGRAVITY SKILLS -->")
    assert b"Global user rule.\r\n" in global_rules
    assert project_rules.startswith(setup.ANTIGRAVITY_POLICY_BEGIN)
    assert project_rules.count(setup.ANTIGRAVITY_POLICY_BEGIN) == 1
    assert "Project user rule." in project_rules
    assert unmanaged.read_text(encoding="utf-8") == "User skill"
    assert "caveman" in setup.COMPANION_SKILLS
    assert "ultra mode" in project_rules


def test_gemini_clean_install_and_repeat_install_real_skills(tmp_path, monkeypatch):
    import hashlib
    import io
    import shutil
    import zipfile

    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("repo/skills/using-superpowers/SKILL.md", "bootstrap")
        archive.writestr("repo/skills/brainstorming/SKILL.md", "workflow")
    payload = data.getvalue()
    monkeypatch.setattr(setup, "SUPERPOWERS_ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(setup, "download_superpowers_archive", lambda: payload)
    monkeypatch.setattr(setup, "json_mcp_merge", lambda *a, **k: None)
    monkeypatch.setattr(setup, "sync_antigravity_mcp_config", lambda *a, **k: None)
    monkeypatch.setattr(setup, "sync_antigravity_config_json", lambda *a, **k: None)
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *a, **k: {})
    install = tmp_path / "install"
    shutil.copytree(ROOT / "skills", install / "skills")
    setup.write_all_generated({}, install)
    gemini = tmp_path / ".gemini"
    gemini.mkdir()
    (gemini / "GEMINI.md").write_bytes(b"User rule one.\r\nUser rule two.\n")
    project = tmp_path / "project"
    for _ in range(2):
        setup.configure_gemini_instance(gemini, install, Path("python"), None, {}, False, True,
                                        project_root=project)
    global_skills = gemini / "config" / "skills"
    assert (gemini / "skills" / "using-superpowers" / "SKILL.md").read_text(encoding="utf-8") == "bootstrap"
    assert (gemini / "skills" / "brainstorming" / "SKILL.md").read_text(encoding="utf-8") == "workflow"
    assert (global_skills / "caveman" / "SKILL.md").is_file()
    assert "ultra" in (global_skills / "caveman" / "SKILL.md").read_text(encoding="utf-8").lower()
    assert (global_skills / "local-ai-orchestrator" / "SKILL.md").is_file()
    assert (gemini / "AGENTS.md").read_text(encoding="utf-8").count(setup.ANTIGRAVITY_POLICY_BEGIN) == 1
    assert (gemini / "GEMINI.md").read_bytes().startswith(b"User rule one.\r\nUser rule two.\n")
    assert (gemini / "AGENTS.md").read_text(encoding="utf-8").startswith(setup.ANTIGRAVITY_POLICY_BEGIN)
    assert (project / "AGENTS.md").read_text(encoding="utf-8").startswith(setup.ANTIGRAVITY_POLICY_BEGIN)


def test_skip_companion_does_not_download_superpowers(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "install_agent_skills", lambda *a, **k: None)
    monkeypatch.setattr(setup, "install_superpowers_skills", lambda *a, **k: pytest.fail("unexpected download"))
    monkeypatch.setattr(setup, "merge_global_policy", lambda *a, **k: None)
    monkeypatch.setattr(setup, "merge_token_economy_policy", lambda *a, **k: None)
    monkeypatch.setattr(setup, "json_mcp_merge", lambda *a, **k: None)
    monkeypatch.setattr(setup, "sync_antigravity_mcp_config", lambda *a, **k: None)
    monkeypatch.setattr(setup, "sync_antigravity_config_json", lambda *a, **k: None)
    monkeypatch.setattr(setup, "build_mcp_entries", lambda *a, **k: {})
    gemini = tmp_path / ".gemini"
    setup.configure_gemini_instance(gemini, tmp_path / "install", Path("python"), None, {}, False, False)
    assert not (gemini / "GEMINI.md").exists()
    assert not (gemini / "AGENTS.md").exists()
