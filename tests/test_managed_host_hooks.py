"""Real host schemas, private steering bounds and reversible owned registration."""
import io
import json
import sys
from pathlib import Path

import pytest

from local_ai_hub.repo_plan.host_adapters import SteeringManager, probe_host_capabilities


def installation(root, host="codex"):
    from local_ai_hub.repo_plan.host_hooks import ManagedHostInstallation
    return ManagedHostInstallation(root, host)


@pytest.mark.parametrize("host,relative,prompt_event", [
    ("codex", ".codex/hooks.json", "UserPromptSubmit"),
    ("gemini_cli", ".gemini/settings.json", "BeforeAgent"),
])
def test_registration_real_schema_preserves_custom_and_rollback(tmp_path, host, relative, prompt_event):
    path = tmp_path / relative
    path.parent.mkdir()
    custom = {"type": "command", "command": "custom-scanner", "timeout": 17}
    path.write_text(json.dumps({"other": {"secret": "preserved"}, "hooks": {
        "SessionStart": [{"hooks": [custom]}]}}))
    manager = installation(tmp_path, host)
    preview = manager.preview()
    assert preview["support_level"] == "advisory"
    assert not (tmp_path / ".local-ai-hub").exists()
    result = manager.apply(expected_revision=preview["revision"])
    assert result["success"]
    config = json.loads(path.read_text())
    assert config["other"] == {"secret": "preserved"}
    assert config["hooks"]["SessionStart"][0]["hooks"] == [custom]
    handler = config["hooks"][prompt_event][0]["hooks"][0]
    assert handler["type"] == "command"
    assert "host_hooks.py" in handler["command"]
    assert handler["timeout"] == (5 if host == "codex" else 5000)
    assert manager.apply(expected_revision=manager.preview()["revision"])["changed"] is False
    # A later user's customization must survive owned rollback.
    config["later"] = 42
    path.write_text(json.dumps(config))
    assert manager.rollback()["success"]
    restored = json.loads(path.read_text())
    assert restored["later"] == 42
    assert restored["hooks"] == {"SessionStart": [{"hooks": [custom]}]}
    assert manager.rollback()["changed"] is False


def test_preview_stale_and_modified_owned_hook_refuse_mutation(tmp_path):
    manager = installation(tmp_path)
    preview = manager.preview()
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text('{"custom": true}')
    with pytest.raises(ValueError, match="changed"):
        manager.apply(expected_revision=preview["revision"])
    manager.apply(expected_revision=manager.preview()["revision"])
    config = json.loads(path.read_text())
    config["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "user-customized"
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="modified"):
        manager.rollback()
    assert path.read_bytes() == before


def test_existing_identical_unowned_configuration_is_never_adopted(tmp_path):
    manager = installation(tmp_path)
    preview = manager.preview()
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"hooks": preview["registrations"]}))
    with pytest.raises(ValueError, match="unowned"):
        manager.apply(expected_revision=manager.preview()["revision"])


def test_config_bounds_and_unsupported_host(tmp_path):
    with pytest.raises(ValueError, match="unsupported"):
        installation(tmp_path, "gemini_antigravity")
    manager = installation(tmp_path)
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_bytes(b" " * 131073)
    with pytest.raises(ValueError, match="large"):
        manager.preview()


def test_corrupt_ownership_manifest_cannot_remove_user_hook(tmp_path):
    manager = installation(tmp_path)
    preview = manager.preview()
    manager.apply(expected_revision=preview["revision"])
    config_path = tmp_path / ".codex/hooks.json"
    config = json.loads(config_path.read_text())
    custom = {"hooks": [{"type": "command", "command": "user-hook"}]}
    config["hooks"]["SessionStart"].append(custom)
    config_path.write_text(json.dumps(config))
    manifest_path = tmp_path / ".local-ai-hub/local/host-adapters/codex.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["groups"] = {"SessionStart": [custom]}
    manifest_path.write_text(json.dumps(manifest))
    before = config_path.read_bytes()
    with pytest.raises(ValueError, match="ownership"):
        manager.rollback()
    assert config_path.read_bytes() == before


def test_steering_lock_serializes_capture_and_fails_closed(tmp_path):
    manager = SteeringManager(tmp_path)
    manager._ensure_dir()
    lock = manager.steering_dir / ".inbox.lock"
    lock.write_text("owned by active writer")
    with pytest.raises(ValueError, match="busy"):
        manager.capture_steering("session", "message", event_id="turn")
    assert manager.list_pending_steering() == []
    assert lock.exists()


def test_host_event_idempotency_and_not_authentic_capability_evidence(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "session-1",
               "turn_id": "turn-1", "cwd": str(tmp_path), "prompt": "Change XML to JSON"}
    first = handle_host_event(tmp_path, "codex", payload)
    second = handle_host_event(tmp_path, "codex", payload)
    assert first == second
    pending = SteeringManager(tmp_path).list_pending_steering(session_id="session-1")
    assert len(pending) == 1
    assert "Change XML" in pending[0]["message"]
    assert first["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert probe_host_capabilities("codex", tmp_path).support_level != "enforced"
    assert SteeringManager(tmp_path).list_pending_steering(session_id="other-session") == []


def test_payloads_do_not_cross_root_or_accept_invalid_shapes(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s",
               "cwd": str(tmp_path.parent), "prompt": "x"}
    with pytest.raises(ValueError, match="root"):
        handle_host_event(tmp_path, "codex", payload)
    payload["cwd"] = str(tmp_path)
    payload["prompt"] = "x" * 17000
    with pytest.raises(ValueError, match="message"):
        handle_host_event(tmp_path, "codex", payload)
    with pytest.raises(ValueError):
        handle_host_event(tmp_path, "codex", [])
    assert not (tmp_path / ".local-ai-hub").exists()


def test_steering_bounds_and_reconciliation_path(tmp_path):
    manager = SteeringManager(tmp_path)
    with pytest.raises(ValueError, match="steering_id"):
        manager.mark_reconciled("../../outside")
    with pytest.raises(ValueError, match="message"):
        manager.capture_steering("s", "x" * 17000)
    for index in range(257):
        path = manager.steering_dir / f"steer_{index:024x}.json"
        path.write_text('{}')
    with pytest.raises(ValueError, match="capacity"):
        manager.capture_steering("s", "bounded")


def test_hook_cli_limits_input_and_emits_only_json(tmp_path, monkeypatch, capsys):
    from local_ai_hub.repo_plan import host_hooks
    monkeypatch.setattr(sys, "stdin", io.StringIO("x" * 65537))
    assert host_hooks.main(["--root", str(tmp_path), "--host", "codex"]) == 1
    assert json.loads(capsys.readouterr().out)["systemMessage"]


def test_no_symlink_config_or_steering_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    try:
        (root / ".codex").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="link"):
        installation(root).preview()
    assert list(outside.iterdir()) == []


def test_superpowers_pinned_manifest_and_install_contract(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import inspect_superpowers
    missing = inspect_superpowers("gemini_cli", tmp_path)
    assert missing["status"] == "missing"
    assert missing["install_argv"][-2:] == ["--ref", "v7.0.1"]
    (tmp_path / "gemini-extension.json").write_text('{"name":"superpowers","version":"7.0.1"}')
    assert inspect_superpowers("gemini_cli", tmp_path)["status"] == "incomplete"
    skill = tmp_path / "skills/using-superpowers/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: using-superpowers\n---\nbootstrap")
    (tmp_path / "GEMINI.md").write_text("Superpowers bootstrap")
    assert inspect_superpowers("gemini_cli", tmp_path)["status"] == "compatible_on_disk"
    (tmp_path / "gemini-extension.json").write_text('{"name":"superpowers","version":"7.0.0"}')
    assert inspect_superpowers("gemini_cli", tmp_path)["status"] == "incompatible"


def test_setup_entrypoint_isolated_preview_apply_rollback(tmp_path):
    from local_ai_hub.process_utils import run_hidden
    setup = Path(__file__).resolve().parents[1] / "tools/setup.py"
    arguments = [sys.executable, str(setup), "--host-project-root", str(tmp_path), "--host-adapter", "codex"]
    preview = run_hidden(arguments, capture_output=True, text=True, timeout=20, max_output_bytes=32768)
    assert preview.returncode == 0, preview.stderr
    data = json.loads(preview.stdout)
    assert data["superpowers"]["status"] == "not_checked"
    assert not (tmp_path / ".local-ai-hub").exists()
    applied = run_hidden(arguments + ["--host-action", "apply", "--host-preview-revision", data["revision"]],
                         capture_output=True, text=True, timeout=20, max_output_bytes=32768)
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["changed"]
    rollback = run_hidden(arguments + ["--host-action", "rollback"], capture_output=True, text=True,
                          timeout=20, max_output_bytes=32768)
    assert rollback.returncode == 0, rollback.stderr
    assert json.loads(rollback.stdout)["changed"]
    assert not (tmp_path / ".codex/hooks.json").exists()


def test_confirm_reconciliation_requires_scoped_actual_revisions(tmp_path):
    manager = SteeringManager(tmp_path)
    steering = manager.capture_steering("session-a", "Revise acceptance", task_id="task-a")["steering_id"]
    arguments = {"task_id": "task-a", "session_id": "session-a", "contract_revision": 2,
                 "plan_revision": "actual-plan-3", "spec_revision": "actual-spec-sha"}
    with pytest.raises(ValueError, match="scope"):
        manager.confirm_reconciled(steering, **{**arguments, "task_id": "task-b"})
    with pytest.raises(ValueError, match="contract_revision"):
        manager.confirm_reconciled(steering, **{**arguments, "contract_revision": ""})
    assert manager.confirm_reconciled(steering, **arguments)
    assert manager.list_pending_steering() == []


def test_dependency_install_explicit_and_bounded(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan import host_hooks
    from local_ai_hub import process_utils
    package = tmp_path / "installed"
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        package.mkdir()
        (package / "gemini-extension.json").write_text('{"name":"superpowers","version":"7.0.1"}')
        skill = package / "skills/using-superpowers/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("bootstrap")
        (package / "GEMINI.md").write_text("bootstrap")
        import subprocess
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(process_utils, "run_hidden", fake_run)
    arguments = dict(repo_root=tmp_path, package_root=package, executable=sys.executable)
    with pytest.raises(ValueError, match="authorization"):
        host_hooks.install_superpowers("gemini_cli", **arguments)
    waiting = host_hooks.install_superpowers("gemini_cli", **arguments, operator_authorized=True)
    assert waiting["requires_consent"] and not calls
    result = host_hooks.install_superpowers("gemini_cli", **arguments, operator_authorized=True, consent=True)
    assert result["success"] and result["dependency"]["compatible"]
    assert calls[0][0][-3:] == ["--ref", "v7.0.1", "--consent"]
    assert calls[0][1]["timeout"] == 60
    assert calls[0][1]["max_output_bytes"] == 65536
    assert calls[0][1]["shell"] is False
    assert host_hooks.install_superpowers("gemini_cli", **arguments, operator_authorized=True, consent=True)["changed"] is False
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Codex"):
        host_hooks.install_superpowers("codex", **arguments, operator_authorized=True, consent=True)


def test_dependency_install_refuses_incompatible_customization(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import install_superpowers
    (tmp_path / "gemini-extension.json").write_text('{"name":"superpowers","version":"custom"}')
    with pytest.raises(ValueError, match="existing"):
        install_superpowers("gemini_cli", repo_root=tmp_path, package_root=tmp_path,
                            executable=sys.executable, operator_authorized=True, consent=True)
