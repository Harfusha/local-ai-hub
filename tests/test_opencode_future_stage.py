import pytest

from local_ai_hub.opencode_hardware import future_profile_candidates, inspect_opencode_hardware


def test_future_profile_candidates_do_not_change_hardware_admission():
    candidates = future_profile_candidates("16gb")
    assert candidates[0] == "qwen2.5-coder:14b"
    assert future_profile_candidates("12gb", model="custom:latest")[0] == "custom:latest"
    assert inspect_opencode_hardware({"gpus": [{"vendor": "nvidia", "vram_mb": 8192}]})["profile"] == "unsupported"
    with pytest.raises(ValueError):
        future_profile_candidates("auto")
    with pytest.raises(ValueError):
        future_profile_candidates("16gb", model="../../model")


def test_future_staging_is_explicitly_unverified(monkeypatch, tmp_path):
    import tools.setup as setup
    import local_ai_hub.opencode_models as models

    for name in ("opencode_goal/index.js", "opencode_goal/core.js", "opencode_goal/transport.js", "opencode_goal/package.json",
                 "opencode_mcp/index.js", "opencode_mcp/package.json", "opencode_pipe_client.cjs",
                 "opencode_sandbox_bootstrap.cjs", "opencode_stop_client.ps1"):
        asset = tmp_path / "tools" / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(setup, "_opencode_platform_supported", lambda: True)
    monkeypatch.setattr(setup._opencode_install_module, "install_windows_x64", lambda path: path / "opencode.exe")
    monkeypatch.setattr(models, "local_inventory", lambda origin: {"qwen2.5-coder:14b"})
    result = setup.stage_opencode_future_profile({"server": {"ollama_url": "http://127.0.0.1:11434"}}, tmp_path,
                                                 destination=tmp_path / "app", target="16gb", allow_pull=False)
    assert result["target_profile"] == "16gb"
    assert result["candidate"] == "qwen2.5-coder:14b"
    assert result["runtime_verified"] is False and result["admission"] == "unverified"
    assert result["complete"] is False and result["selected_model"] is None


def test_future_staging_rejects_missing_adapter_before_install(monkeypatch, tmp_path):
    import tools.setup as setup
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    for name in ("index.js", "core.js", "transport.js", "package.json"):
        (plugin / name).write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(setup, "_opencode_platform_supported", lambda: True)
    monkeypatch.setattr(setup._opencode_install_module, "install_windows_x64", lambda _: pytest.fail("installer was invoked"))
    with pytest.raises(ValueError, match="integration asset.*opencode_mcp"):
        setup.stage_opencode_future_profile({}, tmp_path, destination=tmp_path / "app", target="16gb", allow_pull=False)


def test_staging_cli_is_isolated_from_normal_setup(monkeypatch, tmp_path, capsys):
    import sys
    import tools.setup as setup

    calls = []
    monkeypatch.setattr(sys, "argv", ["setup.py", "--stage-opencode-profile", "16gb", "--opencode-dir", str(tmp_path), "--skip-model-pull"])
    monkeypatch.setattr(setup, "select_config_source", lambda _: (None, {}, tmp_path))
    monkeypatch.setattr(setup, "stage_opencode_future_profile", lambda *args, **kwargs: calls.append(kwargs) or {"complete": False})
    assert setup.main() == 0
    assert calls[0]["target"] == "16gb" and calls[0]["allow_pull"] is False
    assert '"complete": false' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["setup.py", "--stage-opencode-profile", "16gb", "--with-opencode"])
    with pytest.raises(SystemExit):
        setup.main()
    assert len(calls) == 1
