from pathlib import Path

import pytest

from local_ai_hub.generator import generate_opencode_runtime_config
from local_ai_hub.opencode_hardware import inspect_opencode_hardware
from local_ai_hub.opencode_inference_session import ExternalInferenceSession, InferenceSessionError
from local_ai_hub.opencode_models import ensure_model, local_pull
from local_ai_hub.opencode_provider_service import ProviderService


@pytest.mark.parametrize("model", ["gemma4:cloud", "qwen3-coder:480b-cloud", "GPT-OSS:120B-CLOUD", "example-cloud", "model:tag:cloud", "model:cloud:local"])
def test_local_profile_rejects_explicit_cloud_names_before_any_external_action(tmp_path, model, monkeypatch):
    class Scheduler:
        def reserve_external_gpu(self):
            pytest.fail("reserved GPU for cloud model")
    with pytest.raises(InferenceSessionError):
        ExternalInferenceSession.open(Scheduler(), model)
    monkeypatch.setattr("local_ai_hub.opencode_models.require_local_source_version", lambda _: pytest.fail("queried"))
    service = ProviderService(Scheduler(), upstream_url="http://127.0.0.1:11434", hub_token="x" * 40)
    with pytest.raises(InferenceSessionError):
        service.start(model)
    assert service.status()["state"] == "stopped"
    with pytest.raises(ValueError):
        ensure_model(model, inventory=lambda: pytest.fail("queried"), pull=lambda _: pytest.fail("pulled"))
    with pytest.raises(ValueError):
        local_pull("unused", "http://127.0.0.1:11434", model)
    with pytest.raises(ValueError):
        generate_opencode_runtime_config({}, tmp_path, Path("python"), model=model, provider_port=12345, hub_port=11435)
    with pytest.raises(ValueError):
        inspect_opencode_hardware({"gpus": [{"vendor": "nvidia", "vram_mb": 12282}]}, model=model)


@pytest.mark.parametrize("model", ["qwen3.5:9b", "qwen2.5-coder:14b", "example/large:latest"])
def test_local_model_names_remain_available(model):
    result = ensure_model(model, inventory=lambda: {model}, pull=lambda _: pytest.fail("pulled"))
    assert result["installed"] is True
