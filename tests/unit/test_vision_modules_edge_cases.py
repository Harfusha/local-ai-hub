from __future__ import annotations

import pytest

from local_ai_hub.vision_contracts import (
    VisionContextBoundsError,
    _json_text,
    image_dimensions,
    is_valid_bbox,
    is_valid_category,
    is_valid_severity,
    parse_vision_result,
    validate_bounded_context,
)
from local_ai_hub.vision_payload import vision_input_error, vision_success_payload
from local_ai_hub.vision_request import select_vision_model
from local_ai_hub.vision_response import _input_error


def test_vision_contracts_validate_bounded_context_numeric_guards() -> None:
    # NaN, Inf, bool, negative bounds must raise VisionContextBoundsError
    with pytest.raises(VisionContextBoundsError, match="bounds are invalid"):
        validate_bounded_context({"key": "val"}, name="test", max_chars=float("nan"))  # type: ignore[arg-type]

    with pytest.raises(VisionContextBoundsError, match="bounds are invalid"):
        validate_bounded_context({"key": "val"}, name="test", max_chars=True)  # type: ignore[arg-type]

    with pytest.raises(VisionContextBoundsError, match="bounds are invalid"):
        validate_bounded_context({"key": "val"}, name="test", max_field_chars=float("inf"))  # type: ignore[arg-type]

    with pytest.raises(VisionContextBoundsError, match="bounds are invalid"):
        validate_bounded_context({"key": "val"}, name="test", max_depth=-1)


def test_vision_contracts_json_text_and_parse_edge_cases() -> None:
    # Non-string input to _json_text must return empty string without AttributeError
    assert _json_text(None) == ""  # type: ignore[arg-type]
    assert _json_text(12345) == ""  # type: ignore[arg-type]
    assert _json_text({}) == ""  # type: ignore[arg-type]

    # Non-string raw input to parse_vision_result must return terminal error without crashing
    res = parse_vision_result(None)  # type: ignore[arg-type]
    assert res.terminal is True
    assert "error" in res.__dict__ or bool(res.error)

    res2 = parse_vision_result(42)  # type: ignore[arg-type]
    assert res2.terminal is True


def test_vision_contracts_validation_helpers() -> None:
    # Severity validation
    assert is_valid_severity("blocker") is True
    assert is_valid_severity("HIGH") is True
    assert is_valid_severity("  low  ") is True
    assert is_valid_severity("critical") is False
    assert is_valid_severity(None) is False
    assert is_valid_severity(123) is False

    # Category validation
    assert is_valid_category("layout") is True
    assert is_valid_category("ACCESSIBILITY") is True
    assert is_valid_category("unknown_category") is False
    assert is_valid_category(None) is False
    assert is_valid_category(123) is False

    # BBox validation
    assert is_valid_bbox([10, 20, 100, 200]) is True
    assert is_valid_bbox((0, 0, 1920, 1080)) is True
    assert is_valid_bbox([100, 200, 10, 20]) is False  # left > right
    assert is_valid_bbox([10, 200, 100, 20]) is False  # top > bottom
    assert is_valid_bbox([float("nan"), 0, 10, 10]) is False
    assert is_valid_bbox([0, float("inf"), 10, 10]) is False
    assert is_valid_bbox([1, 2, 3]) is False  # not 4 items
    assert is_valid_bbox(None) is False
    assert is_valid_bbox("bbox") is False


def test_vision_payload_edge_cases() -> None:
    # None message or code
    err = vision_input_error(None)  # type: ignore[arg-type]
    assert err["success"] is False
    assert err["error"] == ""

    # vision_success_payload with None raw_output
    payload = vision_success_payload(
        model="qwen3-vl:4b",
        raw_output=None,  # type: ignore[arg-type]
        parsed=object(),
        prompt_context="test",
        image_artifact_id=None,
        bundle_artifact_id=None,
        raw_output_artifact_id=None,
    )
    assert payload["success"] is True
    assert payload["response"] == ""


def test_vision_request_select_model_edge_cases() -> None:
    # None args or None config
    model, err = select_vision_model(None, None)  # type: ignore[arg-type]
    assert isinstance(model, str)
    assert model == "qwen3-vl:4b"
    assert err is None

    # Null bytes in model name
    model2, err2 = select_vision_model({"model": "qwen3-vl:4b\x00"}, {})
    assert "\x00" not in model2
    assert model2 == "qwen3-vl:4b"


def test_vision_response_input_error_edge_cases() -> None:
    err = _input_error(None)  # type: ignore[arg-type]
    assert err["success"] is False
    assert err["error"] == ""
