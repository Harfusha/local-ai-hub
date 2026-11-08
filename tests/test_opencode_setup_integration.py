from pathlib import Path
import sys

import pytest

from tools import setup


def gpu(size):
    return {"gpus": [{"vendor": "nvidia", "vram_mb": size, "name": "GPU"}]}


def test_prepare_components_uses_one_candidate_and_never_claims_runtime(tmp_path, monkeypatch):
    from local_ai_hub import opencode_models
    monkeypatch.setattr(setup, "_opencode_platform_supported", lambda: True)
    monkeypatch.setattr(setup._opencode_install_module, "install_windows_x64", lambda path: path / "opencode.exe")
    monkeypatch.setattr(opencode_models, "local_inventory", lambda origin: {"qwen3.5:9b"})
    monkeypatch.setattr(opencode_models, "local_pull", lambda *args: pytest.fail("downloaded installed model"))
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    cfg = {"server": {"ollama_url": "http://127.0.0.1:11434"}}
    result = setup.prepare_opencode_components(cfg, tmp_path, gpu(12282), destination=tmp_path / "bin", allow_pull=True)
    assert result["candidate"] == "qwen3.5:9b"
    assert result["model"]["downloaded"] is False
    assert result["complete"] is False
    assert result["runtime_verified"] is False


def test_prepare_components_rejects_small_gpu_before_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "_opencode_platform_supported", lambda: True)
    monkeypatch.setattr(setup._opencode_install_module, "install_windows_x64", lambda path: pytest.fail("installed"))
    with pytest.raises(ValueError, match="12"):
        setup.prepare_opencode_components({}, tmp_path, gpu(8188), destination=tmp_path / "bin", allow_pull=False)


def test_with_opencode_cannot_run_generate_only(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["setup.py", "--with-opencode", "--generate-only"])
    with pytest.raises(SystemExit):
        setup.main()


def test_with_opencode_rejects_small_gpu_before_normal_install(monkeypatch):
    from local_ai_hub import hardware
    monkeypatch.setattr(setup, "_opencode_platform_supported", lambda: True)
    monkeypatch.setattr(hardware, "detect_hardware", lambda: gpu(8188))
    monkeypatch.setattr(setup, "select_config_source", lambda *_: pytest.fail("normal installation started"))
    monkeypatch.setattr(sys, "argv", ["setup.py", "--with-opencode"])
    assert setup.main() == 1


def test_prepare_16gb_uses_provisional_9b_without_claiming_selection(tmp_path, monkeypatch):
    from local_ai_hub import opencode_models
    monkeypatch.setattr(setup, "_opencode_platform_supported", lambda: True)
    monkeypatch.setattr(setup._opencode_install_module, "install_windows_x64", lambda path: path / "opencode.exe")
    monkeypatch.setattr(opencode_models, "local_inventory", lambda origin: {"qwen3.5:9b-nvfp4"})
    plugin = tmp_path / "tools" / "opencode_goal"
    plugin.mkdir(parents=True)
    (plugin / "index.js").touch()
    result = setup.prepare_opencode_components({"server": {"ollama_url": "http://127.0.0.1:11434"}}, tmp_path,
                                               gpu(16376), destination=tmp_path / "bin", allow_pull=False)
    assert result["candidate"] == "qwen3.5:9b-nvfp4"
    assert result["complete"] is False and result["runtime_verified"] is False
    assert not any("hub api token" in item.lower() for item in result["pending"])


def test_normal_setup_invokes_opencode_preparation_and_reports_incomplete(tmp_path, monkeypatch, capsys):
    from local_ai_hub import hardware
    cfg = {"features": {"rag": False, "reranker": False, "install_local_nlp_dependencies": False},
           "models": {}, "setup": {}, "headless": {"enabled": False}, "_hardware": gpu(12282)}
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    monkeypatch.setattr(setup, "_opencode_platform_supported", lambda: True)
    monkeypatch.setattr(hardware, "detect_hardware", lambda: gpu(12282))
    monkeypatch.setattr(setup, "select_config_source", lambda _: (config, cfg, tmp_path))
    monkeypatch.setattr(setup, "copy_install_tree", lambda *a, **k: True)
    monkeypatch.setattr(setup, "load_hub_config", lambda _: cfg)
    monkeypatch.setattr(setup, "ensure_venv", lambda _: Path(sys.executable))
    monkeypatch.setattr(setup, "install_requirements", lambda *a, **k: True)
    monkeypatch.setattr(setup, "ensure_ollama_for_setup", lambda *a, **k: True)
    monkeypatch.setattr(setup, "ensure_llama_cpp_for_setup", lambda *a, **k: True)
    monkeypatch.setattr(setup, "pull_ollama_models", lambda current: current["features"]["pull_models_during_setup"] is False or pytest.fail("unrelated pulls enabled"))
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *a, **k: None)
    monkeypatch.setattr(setup, "run", lambda *a, **k: None)
    seen = {}
    def prepare(*args, **kwargs):
        seen.update(kwargs)
        return {"complete": False, "runtime_verified": False, "candidate": "qwen3.5:9b"}
    monkeypatch.setattr(setup, "prepare_opencode_components", prepare)
    monkeypatch.setattr(sys, "argv", ["setup.py", "--with-opencode", "--opencode-dir", str(tmp_path / "bin"),
                                    "--skip-tools", "--skip-agent-config", "--skip-service",
                                    "--skip-token-economy", "--skip-companion-skills", "--skip-model-pull"])
    assert setup.main() == 1
    assert seen["allow_pull"] is False
    assert "OpenCode preparation is incomplete" in capsys.readouterr().out
