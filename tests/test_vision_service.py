from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.services import LocalAIServices


def _services(tmp_path: Path, *, models: dict[str, str] | None = None):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-image")
    runtime = MagicMock()
    runtime.request.return_value = {"response": json.dumps({"summary": "ok", "findings": []})}
    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": models or {},
    }
    services = LocalAIServices(
        config=config,
        runtime=runtime,
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )
    services.artifacts.put.return_value = "art_vision_raw"
    return services, runtime, image


def test_vision_defaults_to_qwen_model_and_requests_json(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path)

    result = services.vision({"image": str(image), "prompt": "Review UI"}, "t")

    assert result["success"] is True
    assert result["model"] == "qwen3-vl:4b"
    payload = runtime.request.call_args.args[1]
    assert payload["format"] == "json"
    assert payload["images"] == ["ZmFrZS1pbWFnZQ=="]


def test_packaged_and_source_defaults_configure_qwen_vision_model() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("defaults.toml", "src/local_ai_hub/defaults.toml"):
        with (root / relative).open("rb") as handle:
            config = tomllib.load(handle)
        assert config["models"]["vision"] == "qwen3-vl:4b"
        assert config["model_execution"]["vision"]["parallel"] == 1


def test_vision_explicit_model_override_is_preserved(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})

    result = services.vision({"image": str(image), "model": "custom-vl:latest"}, "t")

    assert result["model"] == "custom-vl:latest"
    assert runtime.request.call_args.args[1]["model"] == "custom-vl:latest"


def test_vision_bounds_requested_output_tokens(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})

    services.vision({"image": str(image), "max_tokens": 999999}, "t")

    assert runtime.request.call_args.args[1]["options"]["num_predict"] == 4096


def test_vision_returns_structured_findings_and_raw_artifact(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.return_value = {
        "response": json.dumps(
            {
                "summary": "bad CTA",
                "findings": [
                    {
                        "id": "f-1",
                        "severity": "high",
                        "category": "layout",
                        "problem": "CTA overlaps footer",
                        "confidence": 0.9,
                    }
                ],
            }
        )
    }

    result = services.vision({"image": str(image), "prompt": "Review UI"}, "t")

    assert result["review"]["summary"] == "bad CTA"
    assert result["review"]["findings"][0]["finding_id"] == "f-1"
    assert result["raw_output_artifact_id"] == "art_vision_raw"
    services.artifacts.put.assert_called_once()


def test_malformed_vision_output_is_terminal_structured_failure(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.return_value = {"response": "The button looks fine."}

    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["raw_output_artifact_id"] == "art_vision_raw"
    assert "review" not in result


def test_missing_vision_model_is_explicitly_unsupported(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": ""})

    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is False
    assert result["unsupported"] is True
    assert result["degraded"] is True
    assert "qwen3-vl:4b" in result["error"]
    runtime.request.assert_not_called()


def test_missing_model_response_is_only_unsupported_failure(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.return_value = {"error": "HTTP 404: model 'qwen3-vl:4b' not found"}

    result = services.vision({"image": str(image)}, "t")

    assert result["unsupported"] is True
    assert result["degraded"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_vision_timeout_is_retryable_not_unsupported(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.side_effect = TimeoutError("secret timeout detail")

    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is False
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert "unsupported" not in result
    assert "secret timeout detail" not in result["error"]


def test_vision_network_error_is_retryable_not_unsupported(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.return_value = {"error": "Ollama unavailable"}

    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is False
    assert result["retryable"] is True
    assert result["terminal"] is False
    assert "unsupported" not in result


def test_vision_runtime_failure_is_terminal_not_unsupported(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.side_effect = RuntimeError("secret runtime detail")

    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is False
    assert result["retryable"] is False
    assert result["terminal"] is True
    assert "unsupported" not in result
    assert "secret runtime detail" not in result["error"]


def test_vision_file_read_error_is_sanitized(tmp_path: Path, monkeypatch) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})

    def fail_read(_path):
        raise OSError("C:\\private\\secret-image.png")

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "private" not in result["error"]
    assert "secret-image" not in result["error"]
    runtime.request.assert_not_called()


def test_vision_model_has_separate_single_slot_policy(tmp_path: Path) -> None:
    policy = ModelExecutionPolicy(
        {
            "models": {
                "vision": "qwen3-vl:4b",
                "fast_code": "fast",
                "heavy_code": "smart",
                "reasoning": "reasoning",
            },
            "model_execution": {"vision": {"parallel": 1, "context_tokens": 8192}},
        }
    )

    profile = policy.profile("qwen3-vl:4b", role="vision")
    override_profile = policy.profile("custom-vl:latest", role="vision")

    assert policy.tier_for("qwen3-vl:4b") == "vision"
    assert profile.tier == "vision"
    assert profile.parallel_limit == 1
    assert override_profile.tier == "vision"
