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


def test_superpowers_download_retries_rate_limit_with_bounded_backoff(monkeypatch):
    import urllib.error

    class Response:
        read = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read1(self, size):
            if self.read:
                return b""
            self.read = True
            return b"verified archive"

    attempts = []
    delays = []

    def open_archive(*args, **kwargs):
        attempts.append(kwargs["timeout"])
        if len(attempts) < 3:
            raise urllib.error.HTTPError(args[0], 429, "rate limited", {"Retry-After": "1"}, None)
        return Response()

    monkeypatch.setattr(setup.urllib.request, "urlopen", open_archive)
    monkeypatch.setattr(setup, "sleep", delays.append, raising=False)

    assert setup.download_superpowers_archive() == b"verified archive"
    assert attempts == [10, 10, 10]
    assert delays == [1.0, 1.0]


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



def test_sync_antigravity_hooks_json_preserves_custom_and_is_idempotent(tmp_path):
    import json
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(json.dumps({"custom-hook": {"enabled": True, "PreInvocation": []}}), encoding="utf-8")

    fake_python = tmp_path / "bin" / "python.exe"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("", encoding="utf-8")

    setup.sync_antigravity_hooks_json(hooks_file, tmp_path, fake_python, False)
    data = json.loads(hooks_file.read_text(encoding="utf-8"))

    assert "custom-hook" in data
    assert data["custom-hook"]["enabled"] is True
    import os
    assert "local-ai-hub" in data
    assert (tmp_path / ("local-ai-hook.cmd" if os.name == "nt" else "local-ai-hook.sh")).is_file()
    hub_hook = data["local-ai-hub"]
    assert hub_hook["enabled"] is True
    assert len(hub_hook["PreInvocation"]) == 1
    assert "local-ai-hook" in hub_hook["PreInvocation"][0]["command"]
    assert len(hub_hook["PreToolUse"]) == 1
    assert hub_hook["PreToolUse"][0]["matcher"] == "read_file|run_command"
    assert "local-ai-hook" in hub_hook["PreToolUse"][0]["hooks"][0]["command"]

    # Test idempotency
    first_text = hooks_file.read_text(encoding="utf-8")
    setup.sync_antigravity_hooks_json(hooks_file, tmp_path, fake_python, False)
    assert hooks_file.read_text(encoding="utf-8") == first_text


def test_antigravity_hook_pre_invocation():
    from local_ai_hub import antigravity_hook
    res = antigravity_hook.handle_pre_invocation({})
    assert "injectSteps" in res
    assert len(res["injectSteps"]) == 1
    msg = res["injectSteps"][0]["ephemeralMessage"]
    assert "LOCAL AI HUB POLICY" in msg
    assert "call_mcp_tool" in msg
    assert "local_ai_repo" in msg
    assert "local_ai_coord" in msg


def test_antigravity_hook_pre_tool_use_read_file(tmp_path):
    from local_ai_hub import antigravity_hook

    # Whitelisted path
    res = antigravity_hook.handle_pre_tool_use({
        "toolCall": {"name": "read_file", "args": {"Path": str(tmp_path / ".gemini" / "GEMINI.md")}}
    })
    assert res["decision"] == "allow"

    # Slice <= 80 lines allowed
    res = antigravity_hook.handle_pre_tool_use({
        "toolCall": {"name": "read_file", "args": {"Path": "src/foo.py", "StartLine": 1, "EndLine": 80}}
    })
    assert res["decision"] == "allow"

    # Slice > 80 lines denied
    res = antigravity_hook.handle_pre_tool_use({
        "toolCall": {"name": "read_file", "args": {"Path": "src/foo.py", "StartLine": 1, "EndLine": 81}}
    })
    assert res["decision"] == "deny"
    assert "81 lines" in res["reason"]

    # File on disk with >80 lines denied on full read
    large_file = tmp_path / "large.py"
    large_file.write_text("\n".join(f"line_{i} = {i}" for i in range(100)), encoding="utf-8")
    res = antigravity_hook.handle_pre_tool_use({
        "toolCall": {"name": "read_file", "args": {"Path": str(large_file)}}
    })
    assert res["decision"] == "deny"
    assert "100 lines" in res["reason"]

    # File on disk with <=80 lines allowed on full read
    small_file = tmp_path / "small.py"
    small_file.write_text("\n".join(f"line_{i} = {i}" for i in range(20)), encoding="utf-8")
    res = antigravity_hook.handle_pre_tool_use({
        "toolCall": {"name": "read_file", "args": {"Path": str(small_file)}}
    })
    assert res["decision"] == "allow"


def test_antigravity_hook_pre_tool_use_run_command():
    from local_ai_hub import antigravity_hook

    # Unconstrained searches denied
    for bad_cmd in ["dir /s", "dir /s /b", "findstr /s foo *", "grep -r foo .", "rg pattern", "ripgrep test"]:
        res = antigravity_hook.handle_pre_tool_use({
            "toolCall": {"name": "run_command", "args": {"CommandLine": bad_cmd}}
        })
        assert res["decision"] == "deny", f"expected deny for {bad_cmd}"
        assert "prohibited" in res["reason"]

    # Bounded searches or normal commands allowed
    for good_cmd in ["rg -m 5 pattern", "rg --max-count 10 foo", "pytest tests/", "git status", "python -m build"]:
        res = antigravity_hook.handle_pre_tool_use({
            "toolCall": {"name": "run_command", "args": {"CommandLine": good_cmd}}
        })
        assert res["decision"] == "allow", f"expected allow for {good_cmd}"



def test_antigravity_hook_autostart_when_offline_and_cooldown(tmp_path, monkeypatch):
    from local_ai_hub import antigravity_hook
    import urllib.request
    import io

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("LOCAL_AI_STATE_DIR", str(state_dir))

    # Fake hubctl.py
    fake_hubctl = tmp_path / "tools" / "hubctl.py"
    fake_hubctl.parent.mkdir()
    fake_hubctl.write_text("print('started')", encoding="utf-8")

    spawn_calls = []
    def fake_popen(*args, **kwargs):
        spawn_calls.append(args)
        class Dummy:
            pid = 9999
        return Dummy()

    monkeypatch.setattr(antigravity_hook.subprocess, "Popen", fake_popen)

    # When offline:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("connection refused")))

    # 1. Should trigger
    triggered = antigravity_hook._check_and_autostart_hub()
    assert triggered is True
    assert len(spawn_calls) == 1
    assert (state_dir / ".hook_autostart_cooldown").is_file()

    # 2. Cooldown active -> should NOT trigger
    triggered_again = antigravity_hook._check_and_autostart_hub()
    assert triggered_again is False
    assert len(spawn_calls) == 1

    # 3. If service.disabled -> should NOT trigger even after cooldown reset
    (state_dir / ".hook_autostart_cooldown").unlink()
    (state_dir / "service.disabled").write_text("", encoding="utf-8")
    assert antigravity_hook._check_and_autostart_hub() is False
    (state_dir / "service.disabled").unlink()

    # 4. If degraded operational mode -> should NOT trigger
    (state_dir / "operational_mode.json").write_text('{"degraded": true}', encoding="utf-8")
    assert antigravity_hook._check_and_autostart_hub() is False
    (state_dir / "operational_mode.json").unlink()

    # 5. When online -> should NOT trigger
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b'{"success": true}'))
    assert antigravity_hook._check_and_autostart_hub() is False
