import pytest

from local_ai_hub.opencode_hardware import inspect_opencode_hardware


def gpu(vram_mb, **fields):
    return {"vendor": "nvidia", "backend": "cuda", "name": "NVIDIA GPU", "vram_mb": vram_mb, **fields}


def test_auto_profiles_use_dedicated_gpu_memory_and_do_not_claim_admission():
    twelve = inspect_opencode_hardware({"gpus": [gpu(12282)]})
    sixteen = inspect_opencode_hardware({"gpus": [gpu(16376)]})
    assert twelve["profile"] == "12gb"
    assert sixteen["profile"] == "16gb"
    assert twelve["candidates"] == ["qwen3.5:9b", "qwen2.5-coder:7b"]
    assert "qwen2.5-coder:14b" in sixteen["candidates"]
    assert twelve["runtime_verified"] is False
    assert sixteen["selected_model"] is None
    assert sixteen["admission"] == "unverified"
    assert sixteen["reason"] == "runtime_validation_required"


def test_insufficient_unknown_and_integrated_gpus_fail_closed():
    for hardware in ({}, {"gpus": [gpu(8192)]}, {"gpus": [gpu(16376, integrated=True)]}, {"gpus": [gpu("16376")]}, {"gpus": [gpu(True)]}, {"gpus": [gpu(16376, vendor="unknown")]}, {"gpus": [gpu(16376, vendor=[])]}):
        assert inspect_opencode_hardware(hardware)["profile"] == "unsupported"
    assert inspect_opencode_hardware({})["reason"] == "dedicated_gpu_not_detected"
    assert inspect_opencode_hardware({"gpus": [gpu(8192)]})["reason"] == "dedicated_vram_below_12gb"
    assert inspect_opencode_hardware({"gpus": [gpu(0)]})["reason"] == "dedicated_vram_unknown"


def test_explicit_profile_never_upgrades_reported_hardware():
    hardware = {"gpus": [gpu(12282)]}
    with pytest.raises(ValueError, match="16gb"):
        inspect_opencode_hardware(hardware, requested="16gb")
    assert inspect_opencode_hardware({"gpus": [gpu(16376)]}, requested="12gb")["profile"] == "12gb"
    with pytest.raises(ValueError):
        inspect_opencode_hardware(hardware, requested="unknown")
    with pytest.raises(ValueError):
        inspect_opencode_hardware(hardware, requested=[])


def test_multiple_gpus_are_not_pooled_for_model_capacity():
    result = inspect_opencode_hardware({"gpus": [gpu(8188, name="GPU 1"), gpu(8188, name="GPU 2")]})
    assert result["profile"] == "unsupported"


def test_explicit_model_is_only_an_unverified_candidate():
    result = inspect_opencode_hardware({"gpus": [gpu(16376)]}, requested="auto", model="example:14b")
    assert result["candidates"][0] == "example:14b"
    assert result["selected_model"] is None
    assert result["admission"] == "unverified"
    with pytest.raises(ValueError):
        inspect_opencode_hardware({"gpus": [gpu(16376)]}, model=" bad model ")


def test_setup_hardware_inspection_is_read_only(monkeypatch, capsys):
    import json
    import sys
    from local_ai_hub import hardware
    from tools import setup

    monkeypatch.setattr(hardware, "detect_hardware", lambda: {"gpus": [gpu(16376)]})
    monkeypatch.setattr(sys, "argv", ["setup.py", "--inspect-opencode-hardware", "--opencode-profile", "12gb", "--opencode-model", "example:14b"])
    assert setup.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "12gb"
    assert output["candidates"][0] == "example:14b"
    assert output["admission"] == "unverified"
