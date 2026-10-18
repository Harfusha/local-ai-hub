from __future__ import annotations

import inspect

import pytest

from local_ai_hub.vision_inputs import _retired_field_error, prepare_vision_inputs
from local_ai_hub.vision_service import VisionService


@pytest.mark.parametrize("value", [None, False, ""])
def test_vision_input_rejects_retired_tenant_fields_by_presence(value: object) -> None:
    result = prepare_vision_inputs(
        args={"image_artifact_id": "unused", "metadata": {"tenant": value}},
        image_path="",
        prompt="describe",
        artifacts=None,
    )

    assert result["success"] is False
    assert result["error_code"] == "invalid_request"
    assert "tenant" in result["error"]


def test_vision_retired_field_check_handles_nested_collections_and_cycles() -> None:
    request: dict[str, object] = {"prompt": "tenant is ordinary request text"}
    nested: list[object] = [request]
    request["metadata"] = nested
    nested.append({"tenant_id": None})

    assert "tenant_id" in _retired_field_error(request)


def test_vision_retired_field_check_does_not_scan_text_values() -> None:
    assert _retired_field_error({"prompt": "tenant_id belongs to a sample string"}) == ""


def test_vision_service_run_has_no_tenant_parameter() -> None:
    parameters = inspect.signature(VisionService.run).parameters

    assert "tenant" not in parameters
    assert parameters["args"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["cancel_event"].kind is inspect.Parameter.KEYWORD_ONLY


def test_vision_input_preparation_has_no_tenant_parameter() -> None:
    parameters = inspect.signature(prepare_vision_inputs).parameters

    assert "tenant" not in parameters
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters.values())


def test_vision_input_rejects_legacy_tenant_keyword() -> None:
    with pytest.raises(TypeError):
        prepare_vision_inputs(
            args={}, image_path="", prompt="describe", artifacts=None, tenant="legacy"
        )
