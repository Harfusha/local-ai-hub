from __future__ import annotations

from pathlib import Path

import pytest
from local_ai_hub.config import ConfigError, load_config, validate_config
from local_ai_hub.hardware import PROFILE_OVERRIDES, choose_profile, profile_overrides


@pytest.mark.parametrize("probe_hardware,auto_tune", [(False, False), (True, False), (False, True), (True, True)])
def test_hardware_inventory_is_deferred_for_all_transport_configs(
    tmp_path: Path, monkeypatch, probe_hardware: bool, auto_tune: bool,
):
    from local_ai_hub import hardware

    calls = []
    def detect(profile):
        calls.append(profile)
        return {"profile": "cpu", "inventory_marker": "detected"}

    monkeypatch.setattr(hardware, "detect_hardware", detect)
    monkeypatch.setattr(hardware, "profile_overrides", lambda *_args: {"models": {"fast_code": "tuned:test"}})
    path = tmp_path / "manual.toml"
    path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        f'[hardware]\nprofile = "cpu"\nauto_tune = {str(auto_tune).lower()}\n',
        encoding="utf-8",
    )
    cfg = load_config(path, probe_hardware=probe_hardware)
    assert calls == (["cpu"] if probe_hardware else [])
    assert cfg["_hardware"]["profile"] == "cpu"
    if not probe_hardware:
        assert cfg["_hardware"]["inventory_deferred"] is True
    else:
        assert cfg["_hardware"]["inventory_marker"] == "detected"
    assert (cfg["models"]["fast_code"] == "tuned:test") is (probe_hardware and auto_tune)


def _config(tmp_path: Path, extra: str = "", server_bind: str | None = None):
    path = tmp_path / "config.toml"
    bind_line = f'bind = "{server_bind}"\n' if server_bind else ""
    path.write_text(
        f'''[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n{bind_line}[hardware]\nprofile = "cpu"\nauto_tune = true\n{extra}\n''',
        encoding="utf-8",
    )
    return load_config(str(path))


def test_cpu_profile_respects_supported_model_roles(tmp_path: Path):
    cfg = _config(tmp_path)
    assert cfg["_hardware"]["profile"] == "cpu"
    assert cfg["models"]["background_code"] == "qwen2.5-coder:3b"
    assert cfg["models"]["fast_code"] == "qwen2.5-coder:3b"
    assert cfg["models"]["heavy_code"] == "qwen2.5-coder:7b"
    assert cfg["models"]["reasoning"] == "qwen3.5:9b"
    assert cfg["models"]["general"] == "qwen2.5-coder:7b"
    assert cfg["background_gpu"]["enabled"] is False
    assert cfg["features"]["local_reranking"] is True


@pytest.mark.parametrize("profile", ("cpu", "integrated", "low", "balanced", "medium", "high", "max"))
def test_hardware_profiles_do_not_use_preprocess_model_for_inference(profile: str) -> None:
    models = PROFILE_OVERRIDES[profile]["models"]
    inference_roles = ("background_code", "fast_code", "heavy_code", "reasoning", "general")
    assert all(models[role] != "qwen2.5-coder:1.5b" for role in inference_roles)


@pytest.mark.parametrize("profile", ("cpu", "integrated", "low", "balanced", "medium", "high", "max"))
def test_every_hardware_profile_enables_local_reranking(profile: str) -> None:
    assert profile_overrides(profile, {})["features"]["local_reranking"] is True


@pytest.mark.parametrize("profile", ("cpu", "integrated", "low", "balanced", "medium", "high", "max"))
def test_every_nvidia_profile_keeps_auto_retrieval_routes(profile: str) -> None:
    overrides = profile_overrides(
        profile,
        {"gpus": [{"vendor": "nvidia", "vram_mb": 4 * 1024}], "ram": {"total_gb": 32}},
    )
    assert overrides["models"].get("embedding_device", "auto") == "auto"
    assert overrides["models"].get("reranker_device", "auto") == "auto"


def test_background_work_defaults_to_low_os_priority(tmp_path: Path):
    cfg = _config(tmp_path)
    assert cfg["preprocessing"]["cpu_priority"] == "idle"
    assert cfg["background_gpu"]["process_priority"] == "idle"


def test_explicit_model_override_wins(tmp_path: Path):
    cfg = _config(tmp_path, '[models]\nfast_code = "custom:latest"')
    assert cfg["models"]["fast_code"] == "custom:latest"


def test_profile_selection_thresholds():
    assert choose_profile([], 8, "auto") == "cpu"
    assert choose_profile([], 32, "auto") == "low"
    assert choose_profile([{"vendor": "nvidia", "vram_mb": 8 * 1024}], 32, "auto") == "balanced"
    assert choose_profile([{"vendor": "nvidia", "vram_mb": 10 * 1024}], 32, "auto") == "medium"
    assert choose_profile([{"vendor": "nvidia", "vram_mb": 16 * 1024}], 32, "auto") == "high"
    assert choose_profile([{"vendor": "nvidia", "vram_mb": 24 * 1024}], 64, "auto") == "max"
    assert choose_profile([{"vendor": "apple", "unified_memory_mb": 24 * 1024}], 24, "auto") == "medium"
    assert choose_profile([{"vendor": "apple", "unified_memory_mb": 32 * 1024}], 32, "auto") == "high"


@pytest.mark.parametrize("profile", ("high", "max"))
def test_16gb_nvidia_profiles_bound_parallelism_and_keep_auto_retrieval(profile: str):
    overrides = profile_overrides(
        profile,
        {"gpus": [{"vendor": "nvidia", "vram_mb": 16_303}], "ram": {"total_gb": 32}},
    )

    assert overrides["scheduler"]["max_parallel"] == 2
    assert overrides["ollama"]["num_parallel"] == 2
    assert overrides["ollama"]["kv_cache_type"] == ("q4_0" if profile == "high" else "q8_0")
    assert overrides["llama_cpp"]["cache_type_k"] == ("q4_0" if profile == "high" else "q8_0")
    assert overrides["llama_cpp"]["cache_type_v"] == ("q4_0" if profile == "high" else "q8_0")
    assert overrides["models"].get("embedding_device", "auto") == "auto"
    assert overrides["models"].get("reranker_device", "auto") == "auto"
    assert overrides["model_execution"]["smart"]["context_tokens"] == 65_536
    assert overrides["model_execution"]["smart"]["parallel"] == 1
    retired_models = {"qwen3.5:4b-q4_K_M", "gemma4:12b"}
    assert retired_models.isdisjoint(overrides["models"].values())


@pytest.mark.parametrize("key", ("cache_type_k", "cache_type_v"))
def test_config_rejects_unknown_llama_cpp_kv_cache_type(key: str):
    with pytest.raises(ConfigError, match=f"llama_cpp\\.{key}"):
        validate_config({"llama_cpp": {key: "q9_0"}})


def test_high_profile_without_nvidia_does_not_force_cuda_retrieval():
    overrides = profile_overrides("high", {"gpus": [], "ram": {"total_gb": 32}})
    assert "embedding_device" not in overrides["models"]
    assert "reranker_device" not in overrides["models"]


def test_security_validation_refuses_unconfigured_remote_bind(tmp_path: Path):
    with pytest.raises(ConfigError, match="server.bind must be 127.0.0.1"):
        _config(tmp_path, server_bind="0.0.0.0")


def test_health_probe_timeout_rejects_absurd_values(tmp_path: Path):
    with pytest.raises(ConfigError, match="headless.health_probe_timeout_seconds must be <= 5"):
        _config(tmp_path, '[headless]\nhealth_probe_timeout_seconds = 3600\n')


@pytest.mark.parametrize("value", ["true", "false"])
def test_security_validation_rejects_removed_remote_access_option(tmp_path: Path, value: str):
    with pytest.raises(ConfigError, match="security.allow_remote was removed"):
        _config(tmp_path, f"[security]\nallow_remote = {value}\n")


def test_security_validation_rejects_removed_client_host_option(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\nclient_host = "remote.example"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="server.client_host was removed"):
        load_config(str(path))


@pytest.mark.parametrize(
    ("key", "value"),
    [("allowed_hosts", '["remote.example"]'), ("allowed_origins", '["https://remote.example"]')],
)
def test_security_validation_rejects_host_and_origin_overrides(tmp_path: Path, key: str, value: str):
    with pytest.raises(ConfigError, match=f"security.{key} was removed"):
        _config(tmp_path, f"[security]\n{key} = {value}\n")


def test_security_validation_rejects_alternate_loopback_bind(tmp_path: Path):
    with pytest.raises(ConfigError, match="server.bind must be 127.0.0.1"):
        _config(tmp_path, server_bind="localhost")


def test_high_profile_background_ollama_avoids_mcp_http_port(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[hardware]\nprofile = "high"\nauto_tune = false\n'
        '[mcp_http]\nenabled = true\nport = 11436\n',
        encoding="utf-8",
    )
    cfg = load_config(str(path), probe_hardware=False)

    background_port = cfg["background_gpu"]["ollama_url"].rsplit(":", 1)[-1]
    assert background_port != str(cfg["mcp_http"]["port"])


def test_model_routes_match_install_update_prompts_and_capability_matrix():
    root = Path(__file__).resolve().parents[1]
    roles = ("background_code", "fast_code", "heavy_code", "reasoning", "general", "vision")
    for name in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md"):
        prompt = (root / "docs" / name).read_text(encoding="utf-8")
        for profile in PROFILE_OVERRIDES:
            route = "/".join(PROFILE_OVERRIDES[profile]["models"][role] for role in roles)
            preprocess_model = PROFILE_OVERRIDES[profile].get("preprocessing", {}).get("model", "<default>")
            assert f"{profile}={route}" in prompt
            assert f"{profile}={preprocess_model}" in prompt

    capability_doc = (root / "docs" / "MODEL_CAPABILITIES.md").read_text(encoding="utf-8")
    for profile in PROFILE_OVERRIDES:
        row = "| `" + profile + "` | " + " | ".join(
            f"`{PROFILE_OVERRIDES[profile]['models'][role]}`" for role in roles
        ) + " |"
        assert row in capability_doc
        preprocess_model = PROFILE_OVERRIDES[profile].get("preprocessing", {}).get("model", "<default>")
        assert f"{profile}=`{preprocess_model}`" in capability_doc


def test_fp4_detection_and_model_overrides():
    overrides = profile_overrides(
        "high",
        {"gpus": [{"vendor": "nvidia", "vram_mb": 16_303, "compute_cap": 12.0, "has_fp4": True}], "ram": {"total_gb": 32}},
    )
    assert overrides["models"]["general"] == "qwen3.5:9b-nvfp4"
    assert overrides["models"]["heavy_code"] == "qwen2.5-coder:14b"
