from __future__ import annotations

import json
import threading
from typing import Any
from unittest.mock import MagicMock

from local_ai_hub.services import LocalAIServices
from local_ai_hub.vision_service import VisionService


class _Runtime:
    def __init__(
        self,
        cancel_event: threading.Event | None = None,
        *,
        cancel_on_show: bool = False,
    ) -> None:
        self.cancel_event = cancel_event
        self.cancel_on_show = cancel_on_show
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def request(self, endpoint: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        self.calls.append((endpoint, payload, timeout))
        if endpoint == "/api/show":
            if self.cancel_on_show and self.cancel_event is not None:
                self.cancel_event.set()
            return {"capabilities": ["completion", "vision"]}
        if self.cancel_event is not None:
            self.cancel_event.set()
        return {
            "response": json.dumps(
                {
                    "summary": "A clear page.",
                    "findings": [],
                    "unknowns": [],
                    "recommended_checks": [],
                }
            )
        }


class _Artifacts:
    def __init__(self) -> None:
        self.put_calls: list[tuple[Any, ...]] = []

    def put(self, *args: Any) -> str:
        self.put_calls.append(args)
        return "vision-output-artifact"


class _ModelPolicy:
    def __init__(self) -> None:
        self.models: list[str] = []

    def apply_payload(
        self, model: str, payload: dict[str, Any], **_kwargs: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.models.append(model)
        return payload, {"model": model}


def _service(runtime: _Runtime, artifacts: _Artifacts) -> VisionService:
    return VisionService(
        config={"models": {"vision": "local-vl"}},
        runtime=runtime,
        artifacts=artifacts,
        model_policy=_ModelPolicy(),
        repo_tools=None,
        max_output_tokens=4096,
    )


def test_cancelled_before_input_preparation_skips_runtime_and_artifacts() -> None:
    event = threading.Event()
    event.set()
    runtime = _Runtime()
    artifacts = _Artifacts()

    result = _service(runtime, artifacts).run(
        {"image": "data:image/png;base64,ZmFrZQ=="}, "tenant-a", cancel_event=event
    )

    assert result == VisionService.cancelled_result()
    assert runtime.calls == []
    assert artifacts.put_calls == []


def test_cancellation_after_preflight_skips_generation_and_artifact_write() -> None:
    event = threading.Event()
    runtime = _Runtime(event, cancel_on_show=True)
    artifacts = _Artifacts()

    result = _service(runtime, artifacts).run(
        {"image": "data:image/png;base64,ZmFrZQ=="}, "tenant-a", cancel_event=event
    )

    assert result == VisionService.cancelled_result("local-vl")
    assert [call[0] for call in runtime.calls] == ["/api/show"]
    assert artifacts.put_calls == []


def test_cancellation_after_generation_discards_output_before_artifact_write() -> None:
    event = threading.Event()
    runtime = _Runtime(event)
    artifacts = _Artifacts()

    result = _service(runtime, artifacts).run(
        {"image": "data:image/png;base64,ZmFrZQ=="}, "tenant-a", cancel_event=event
    )

    assert result == VisionService.cancelled_result("local-vl")
    assert [call[0] for call in runtime.calls] == ["/api/show", "/api/generate"]
    assert artifacts.put_calls == []


def test_success_preserves_runtime_phase_order_and_output_artifact() -> None:
    runtime = _Runtime()
    artifacts = _Artifacts()

    result = _service(runtime, artifacts).run(
        {"image": "data:image/png;base64,ZmFrZQ==", "prompt": "Review UI"}, "tenant-a"
    )

    assert result["success"] is True
    assert result["model"] == "local-vl"
    assert result["raw_output_artifact_id"] == "vision-output-artifact"
    assert [call[0] for call in runtime.calls] == ["/api/show", "/api/generate"]
    assert runtime.calls[0][2] <= 1.0
    assert len(artifacts.put_calls) == 1
    assert artifacts.put_calls[0][1:] == ("tenant-a", "vision-output")


def test_default_schema_keeps_closed_root_and_finding_objects() -> None:
    schema = VisionService.default_schema()

    assert schema["additionalProperties"] is False
    finding = schema["properties"]["findings"]["items"]
    assert finding["additionalProperties"] is False
    assert "observation_facts" in finding["required"]


def test_public_vision_boundary_observes_replaced_call_time_dependencies(tmp_path) -> None:
    original_runtime = _Runtime()
    replacement_runtime = _Runtime()
    original_artifacts = _Artifacts()
    replacement_artifacts = _Artifacts()
    replacement_policy = _ModelPolicy()
    initial_config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"vision": "original-vl"},
    }
    services = LocalAIServices(
        config=initial_config,
        runtime=original_runtime,
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=original_artifacts,
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )

    first = services.vision(
        {"image": "data:image/png;base64,ZmFrZQ=="}, "tenant-a"
    )
    services.config = {
        **initial_config,
        "models": {"vision": "replacement-vl"},
    }
    services.runtime = replacement_runtime
    services.artifacts = replacement_artifacts
    services.model_policy = replacement_policy
    second = services.vision(
        {"image": "data:image/png;base64,ZmFrZQ=="}, "tenant-a"
    )
    services.config = {
        **services.config,
        "features": {"vision": False},
    }
    third = services.vision(
        {"image": "data:image/png;base64,ZmFrZQ=="}, "tenant-a"
    )

    assert first["success"] is True
    assert second["success"] is True
    assert [call[0] for call in original_runtime.calls] == ["/api/show", "/api/generate"]
    assert [call[0] for call in replacement_runtime.calls] == ["/api/show", "/api/generate"]
    assert replacement_runtime.calls[0][1] == {"name": "replacement-vl"}
    assert len(original_artifacts.put_calls) == 1
    assert len(replacement_artifacts.put_calls) == 1
    assert replacement_policy.models == ["replacement-vl"]
    assert third["error_code"] == "vision_disabled"
    assert len(replacement_runtime.calls) == 2
