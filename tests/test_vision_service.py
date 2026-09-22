from __future__ import annotations

import base64
import json
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.app import LocalAIApp
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.services import LocalAIServices
from local_ai_hub.vision_contracts import VISION_MAX_IMAGE_BYTES, VISION_MAX_IMAGE_CHARS


def _services(tmp_path: Path, *, models: dict[str, str] | None = None):
    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-image")
    runtime = MagicMock()
    runtime.request.return_value = {"response": json.dumps({"summary": "ok", "findings": []})}
    def request(endpoint, payload=None, timeout=None):
        if endpoint == "/api/show":
            return {"capabilities": ["completion", "vision"]}
        return runtime.request.return_value
    runtime.request.side_effect = request
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


def test_vision_normalizes_data_url_to_provider_base64(tmp_path: Path) -> None:
    services, runtime, _image = _services(tmp_path)

    result = services.vision(
        {"image": "data:image/png;base64,ZmFrZS1pbWFnZQ==", "prompt": "Review UI"},
        "t",
    )

    assert result["success"] is True
    assert runtime.request.call_args.args[1]["images"] == ["ZmFrZS1pbWFnZQ=="]


def test_vision_cloud_fallback_is_explicitly_disabled_by_default(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path)

    result = services.vision({"image": str(image), "cloud_fallback": True}, "tenant")

    assert result["success"] is False
    assert result["error_code"] == "vision_cloud_fallback_disabled"
    runtime.request.assert_not_called()


def test_vision_cloud_fallback_enabled_without_provider_fails_closed(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path)
    services.config["vision"] = {"cloud_fallback_enabled": True, "cloud_provider": ""}

    result = services.vision({"image": str(image), "cloud_fallback": True}, "tenant")

    assert result["success"] is False
    assert result["error_code"] == "vision_cloud_fallback_unavailable"
    runtime.request.assert_not_called()


def test_vision_feature_can_be_disabled(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path)
    services.config["features"] = {"vision": False}

    result = services.vision({"image": str(image)}, "tenant")

    assert result["success"] is False
    assert result["unsupported"] is True
    assert result["error_code"] == "vision_disabled"
    runtime.request.assert_not_called()


def test_vision_image_path_checks_size_before_reading_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services, runtime, image = _services(tmp_path)
    image.write_bytes(b"x" * (VISION_MAX_IMAGE_BYTES + 1))

    def fail_read(_self: Path) -> bytes:
        raise AssertionError("oversized image was read before preflight")

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    result = services.vision({"image": str(image), "prompt": "Review UI"}, "tenant-a")

    assert result["terminal"] is True
    assert result["error_code"] == "vision_image_too_large"
    runtime.request.assert_not_called()


def test_vision_rejects_oversized_inline_context_before_json_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    raw = json.dumps({"runtime": "x" * 12_000})
    original_loads = json.loads

    def fail_if_called(value: object, *args: object, **kwargs: object) -> object:
        if value is raw:
            raise AssertionError("oversized inline JSON reached json.loads")
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", fail_if_called)
    result = services.vision({"image": str(image), "runtime": raw}, "tenant-a")

    assert result["terminal"] is True
    assert result["error"]["code"] == "frontend_context_too_large"
    assert runtime.request.call_count == 0


@pytest.mark.parametrize("field_name", ["dom", "accessibility", "computed_styles", "runtime"])
def test_vision_rejects_deep_inline_context_before_parser_recursion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field_name: str
) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    raw = '{"next":' * 32 + "{}" + "}" * 32
    original_loads = json.loads

    def fail_with_recursion(value: object, *args: object, **kwargs: object) -> object:
        if value == raw:
            raise RecursionError("simulated parser recursion")
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", fail_with_recursion)
    result = services.vision({"image": str(image), field_name: raw}, "tenant-a")

    assert result["terminal"] is True
    assert result["error"]["code"] == "frontend_context_too_deep"
    assert runtime.request.call_count == 0


def test_vision_resolves_network_artifact_with_console_ref_for_tenant(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    services.artifacts.get.side_effect = [
        {"success": True, "text": json.dumps({"errors": ["console error"]})},
        {"success": True, "text": json.dumps({"requests": ["/api/items"]})},
    ]
    runtime.request.return_value = {
        "response": json.dumps(
            {
                "summary": "runtime context",
                "findings": [
                    {
                        "id": "f-1",
                        "severity": "medium",
                        "category": "runtime",
                        "problem": "request failed",
                        "observed": "network request is present",
                        "hypothesized": "backend response blocks render",
                        "uncertainty": ["response body not captured"],
                        "confidence": 0.7,
                    }
                ],
            }
        )
    }

    result = services.vision(
        {
            "image": str(image),
            "runtime_artifact_id": "console-1",
            "network_artifact_id": "network-1",
        },
        "tenant-a",
    )

    assert result["success"] is True
    payload = runtime.request.call_args.args[1]
    assert "console error" in payload["prompt"]
    assert "/api/items" in payload["prompt"]
    assert result["coder_context"]["artifact_refs"]["runtime"] == {
        "console_artifact_id": "console-1",
        "network_artifact_id": "network-1",
    }
    assert all(call.kwargs["tenant"] == "tenant-a" for call in services.artifacts.get.call_args_list)


def test_vision_rejects_oversized_inline_dom_like_artifact_ref(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})

    result = services.vision(
        {
            "image": str(image),
            "dom": {
                "redaction": "none",
                "html": "x" * 12_001,
                "elements": [{"element_id": "root"}],
            },
        },
        "tenant-a",
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["error_code"] == "frontend_context_too_large"
    runtime.request.assert_not_called()


def test_packaged_and_source_defaults_configure_qwen_vision_model() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("defaults.toml", "src/local_ai_hub/defaults.toml"):
        with (root / relative).open("rb") as handle:
            config = tomllib.load(handle)
        assert config["models"]["vision"] == "qwen3-vl:4b"


def test_packaged_defaults_enable_vision_capability() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (root / "defaults.toml", root / "src" / "local_ai_hub" / "defaults.toml"):
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        assert config["features"]["vision"] is True
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


def test_vision_stat_error_never_forwards_path_to_ollama(tmp_path: Path, monkeypatch) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})

    def fail_stat(_path):
        raise OSError("C:\\private\\stat-secret.png")

    monkeypatch.setattr(Path, "is_file", fail_stat)
    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "stat-secret" not in result["error"]
    assert "private" not in result["error"]
    runtime.request.assert_not_called()


def test_vision_missing_image_artifact_is_explicit_and_safe(tmp_path: Path) -> None:
    services, runtime, _image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    services.artifacts.get_binary.return_value = {
        "success": False,
        "error": "artifact not found or expired",
        "artifact_id": "img-secret-id",
    }

    result = services.vision({"image_artifact_id": "img-secret-id"}, "t")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "not found" in result["error"].lower()
    assert "img-secret-id" not in result["error"]
    services.artifacts.get_binary.assert_called_once_with("img-secret-id", tenant="t")
    runtime.request.assert_not_called()


def test_vision_rejects_truncated_image_artifact(tmp_path: Path) -> None:
    services, runtime, _image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    services.artifacts.get_binary.return_value = {
        "success": True,
        "mime_type": "image/png",
        "encoding": "base64",
        "data_base64": "cGFydGlhbA==",
        "size_bytes": 60_000,
    }

    result = services.vision({"image_artifact_id": "img-1"}, "t")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "truncated" in result["error"].lower()
    assert result["error_code"] == "vision_artifact_truncated"
    runtime.request.assert_not_called()


def test_vision_accepts_valid_image_at_byte_limit_with_larger_base64_transport(tmp_path: Path) -> None:
    services, runtime, _image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    image_bytes = b"x" * VISION_MAX_IMAGE_BYTES
    encoded = base64.b64encode(image_bytes).decode("ascii")
    services.artifacts.get_binary.return_value = {
        "success": True,
        "mime_type": "image/png",
        "encoding": "base64",
        "data_base64": encoded,
        "size_bytes": len(image_bytes),
    }

    result = services.vision({"image_artifact_id": "img-1"}, "tenant")

    assert result["success"] is True
    assert len(runtime.request.call_args.args[1]["images"][0]) == len(encoded)
    assert len(encoded) > VISION_MAX_IMAGE_CHARS - 1


def test_vision_reports_base64_transport_bound_separately(tmp_path: Path) -> None:
    services, runtime, _image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    encoded = base64.b64encode(b"small-image").decode("ascii") + ("A" * VISION_MAX_IMAGE_CHARS)
    services.artifacts.get_binary.return_value = {
        "success": True,
        "mime_type": "image/png",
        "encoding": "base64",
        "data_base64": encoded,
        "size_bytes": len(b"small-image"),
    }

    result = services.vision({"image_artifact_id": "img-1"}, "tenant")

    assert result["success"] is False
    assert result["error_code"] == "vision_image_transport_too_large"
    assert "transport" in result["error"].lower()
    runtime.request.assert_not_called()


def test_vision_artifact_backend_failure_is_retryable_and_safe(tmp_path: Path) -> None:
    services, runtime, _image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    services.artifacts.get_binary.side_effect = RuntimeError("C:\\private\\artifact-db-secret")

    result = services.vision({"image_artifact_id": "img-1"}, "t")

    assert result["success"] is False
    assert result["terminal"] is False
    assert result["retryable"] is True
    assert "artifact-db-secret" not in result["error"]
    assert "private" not in result["error"]
    runtime.request.assert_not_called()


def test_vision_resolves_binary_screenshot_and_bundle_text_refs(tmp_path: Path) -> None:
    services, runtime, _image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    artifacts = ArtifactStore(tmp_path / "artifacts")
    screenshot_id = artifacts.put_bytes(b"binary-image", "tenant", "vision-image", "image/png")
    dom_id = artifacts.put_json(
        {
            "redaction": "none",
            "html": "<main><button>Save</button></main>",
            "elements": [{"element_id": "root", "tag": "main"}],
        },
        "tenant",
        "live-dom",
    )
    accessibility_id = artifacts.put("button Save is reachable", "tenant", "accessibility")
    styles_id = artifacts.put("button { color: red; }", "tenant", "computed-styles")
    bundle_id = artifacts.put_json(
        {
            "schema_version": "1",
            "screenshot": {"artifact_id": screenshot_id, "mime_type": "image/png"},
            "dom": {"artifact_id": dom_id, "format": "live-dom", "redaction": "none"},
            "accessibility": {"artifact_id": accessibility_id},
            "computed_styles": {"artifact_id": styles_id, "scope": "visible-elements"},
        },
        "tenant",
        "frontend_review_bundle",
    )
    services.artifacts = artifacts

    result = services.vision({"bundle_artifact_id": bundle_id}, "tenant")

    assert result["success"] is True
    payload = runtime.request.call_args.args[1]
    assert payload["images"] == ["YmluYXJ5LWltYWdl"]
    assert "<main><button>Save</button></main>" in payload["prompt"]
    assert "button Save is reachable" in payload["prompt"]
    assert "button { color: red; }" in payload["prompt"]
    assert result["image_artifact_id"] == screenshot_id

    cross_tenant = services.vision({"bundle_artifact_id": bundle_id}, "other-tenant")
    assert cross_tenant["success"] is False
    assert cross_tenant["error_code"] == "vision_input_error"


def test_vision_bundle_artifact_is_resolved_with_bounded_context(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    services.artifacts.get.return_value = {
        "success": True,
        "text": "bundle context",
    }

    result = services.vision(
        {"image": str(image), "bundle_artifact_id": "bundle-1"},
        "t",
    )

    assert result["success"] is True
    services.artifacts.get.assert_called_once()
    assert services.artifacts.get.call_args.kwargs["max_chars"] <= 12000
    assert "bundle context" in runtime.request.call_args.args[1]["prompt"]


def test_vision_rejects_unbounded_prompt_schema_and_image(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})

    prompt_result = services.vision(
        {"image": str(image), "prompt": "P" * 100_000},
        "t",
    )

    assert prompt_result["success"] is False
    assert prompt_result["terminal"] is True
    assert prompt_result["error_code"] == "frontend_prompt_too_large"

    schema_result = services.vision(
        {
            "json_schema": {"description": "S" * 20_000},
            "image": str(image),
        },
        "t",
    )
    image_result = services.vision({"image": "A" * (VISION_MAX_IMAGE_CHARS + 1)}, "t")

    assert schema_result["success"] is False
    assert schema_result["terminal"] is True
    assert schema_result["retryable"] is False
    assert "bounded" in schema_result["error"].lower()
    assert image_result["success"] is False
    assert image_result["terminal"] is True
    assert image_result["retryable"] is False
    assert "bounded" in image_result["error"].lower()


def test_vision_bounds_runtime_and_parsed_text(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.return_value = {
        "response": json.dumps(
            {
                "summary": "S" * 12_000,
                "findings": [
                    {
                        "id": "f-1",
                        "severity": "high",
                        "category": "layout",
                        "problem": "P" * 12_000,
                        "confidence": 0.9,
                        "evidence": ["E" * 12_000],
                        "likely_cause": "C" * 12_000,
                        "fix_hint": "F" * 12_000,
                    }
                ],
            }
        )
    }

    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is True
    assert len(result["response"]) <= 12_000
    finding = result["review"]["findings"][0]
    assert len(result["review"]["summary"]) <= 2_000
    assert len(finding["problem"]) <= 2_000
    assert len(finding["evidence"][0]) <= 2_000
    assert len(finding["likely_cause"]) <= 2_000
    assert len(finding["fix_hint"]) <= 2_000
    stored = services.artifacts.put.call_args.args[0]
    assert len(stored) <= 64_000


def test_vision_rejects_oversized_runtime_output_without_echo(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})
    runtime.request.return_value = {"response": "R" * 100_000}

    result = services.vision({"image": str(image)}, "t")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "bounded" in result["error"].lower()
    assert "response" not in result
    assert len(services.artifacts.put.call_args.args[0]) <= 64_000


def test_text_only_vision_override_is_explicitly_unsupported(tmp_path: Path) -> None:
    services, runtime, image = _services(tmp_path, models={"vision": "qwen3-vl:4b"})

    def text_only_request(endpoint, payload=None, timeout=None):
        if endpoint == "/api/show":
            return {"capabilities": ["completion"]}
        return {"response": json.dumps({"summary": "unexpected", "findings": []})}

    runtime.request.side_effect = text_only_request
    result = services.vision({"image": str(image), "model": "text-only:latest"}, "t")

    assert result["success"] is False
    assert result["unsupported"] is True
    assert result["degraded"] is True
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "vision" in result["error"].lower()
    assert len(runtime.request.call_args_list) == 1
    assert runtime.request.call_args.args[0] == "/api/show"
    assert runtime.request.call_args.args[1] == {"name": "text-only:latest"}


def test_capabilities_expose_configured_vision_model() -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"models": {"vision": "custom-vl:latest"}}
    app.external_tools = MagicMock()
    app.external_tools.status.return_value = {}

    capabilities = app.capabilities()

    assert capabilities["models"]["vision"] == "custom-vl:latest"


def test_capabilities_hide_disabled_vision() -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"features": {"vision": False}, "models": {"vision": "custom-vl:latest"}}
    app.external_tools = MagicMock()
    app.external_tools.status.return_value = {}

    capabilities = app.capabilities()

    assert capabilities["features"]["vision"] is False
    assert capabilities["models"]["vision"] == ""


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
