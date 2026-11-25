from __future__ import annotations

from typing import Any

from local_ai_hub.services import LocalAIServices


class _Artifacts:
    @staticmethod
    def compact(result: dict[str, Any], *, kind: str) -> dict[str, Any]:
        assert kind == "compress"
        return result


def _service() -> LocalAIServices:
    service = object.__new__(LocalAIServices)
    service.config = {
        "models": {
            "general": "qwen3.5:9b-nvfp4",
            "fast_code": "qwen3.5:4b-nvfp4",
        },
        "deterministic": {"compression": False},
        "token_saving": {"compression_chunk_tokens": 4096},
    }
    service.deterministic = None
    service.artifacts = _Artifacts()
    service.generated_models = []

    def generate(model: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        service.generated_models.append(model)
        return {"success": True, "text": "summary"}

    service._generate = generate
    return service


def test_compress_fast_code_role_uses_configured_fast_model() -> None:
    service = _service()

    result = service.compress({"text": "repository search findings", "model_role": "fast_code"})

    assert result["success"] is True
    assert result["model"] == "qwen3.5:4b-nvfp4"
    assert service.generated_models == ["qwen3.5:4b-nvfp4"]


def test_compress_integrated_profile_uses_foreground_fast_model_by_default() -> None:
    service = _service()
    service.config["models"]["background_code"] = "qwen2.5-coder:0.5b"
    service.config["_hardware"] = {"profile": "integrated"}

    result = service.compress({"text": "repository search findings"})

    assert result["success"] is True
    assert service.generated_models == ["qwen3.5:4b-nvfp4"]


def test_compress_falls_back_once_on_resource_pressure() -> None:
    service = _service()
    service.config["models"]["compression_fallback"] = "qwen2.5-coder:1.5b"
    service.config["_hardware"] = {"profile": "integrated"}

    def generate(model: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        service.generated_models.append(model)
        if model == "qwen3.5:4b-nvfp4":
            return {
                "success": False,
                "error_code": "model_empty_response",
                "last_admission_reason": "resource_pressure",
            }
        return {"success": True, "model": model, "text": "summary"}

    service._generate = generate

    result = service.compress({"text": "repository status"})

    assert result["success"] is True
    assert result["model"] == "qwen2.5-coder:1.5b"
    assert result["model_fallback"] == {
        "from": "qwen3.5:4b-nvfp4",
        "to": "qwen2.5-coder:1.5b",
        "reason": "resource_pressure",
    }
    assert service.generated_models == ["qwen3.5:4b-nvfp4", "qwen2.5-coder:1.5b"]


def test_compress_does_not_fallback_for_explicit_model() -> None:
    service = _service()
    service.config["models"]["compression_fallback"] = "qwen2.5-coder:1.5b"
    calls: list[str] = []

    def generate(model: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append(model)
        return {
            "success": False,
            "error_code": "model_empty_response",
            "last_admission_reason": "resource_pressure",
        }

    service._generate = generate

    result = service.compress({
        "text": "repository status",
        "model": "qwen3.5:4b-nvfp4",
    })

    assert result["success"] is False
    assert calls == ["qwen3.5:4b-nvfp4"]


def test_compress_rejects_unknown_model_role_before_generation() -> None:
    service = _service()

    result = service.compress({"text": "repository search findings", "model_role": "unconfigured"})

    assert result["success"] is False
    assert result["terminal"] is True
    assert service.generated_models == []


def test_compress_explicit_model_must_match_configured_route() -> None:
    service = _service()

    result = service.compress({"text": "repository search findings", "model": "qwen3.5:4b-nvfp4"})

    assert result["success"] is True
    assert result["model"] == "qwen3.5:4b-nvfp4"
    assert service.generated_models == ["qwen3.5:4b-nvfp4"]


def test_compress_rejects_unconfigured_model_before_generation() -> None:
    service = _service()

    result = service.compress({"text": "repository search findings", "model": "unconfigured-model"})

    assert result["success"] is False
    assert result["terminal"] is True
    assert service.generated_models == []
