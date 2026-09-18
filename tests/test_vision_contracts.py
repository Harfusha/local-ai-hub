import pytest

from local_ai_hub.vision_contracts import (
    FrontendReviewBundle,
    build_coder_packet,
    parse_vision_result,
)


def test_bundle_requires_screenshot_and_preserves_full_dom() -> None:
    bundle = FrontendReviewBundle.from_payload(
        {
            "schema_version": "1",
            "source": "current_tab",
            "prompt": "Why is the CTA hidden?",
            "screenshot": {"artifact_id": "art_img", "mime_type": "image/png"},
            "dom": {"artifact_id": "art_dom", "redaction": "none"},
        }
    )

    assert bundle.screenshot_artifact_id == "art_img"
    assert bundle.dom_artifact_id == "art_dom"
    assert bundle.dom_redaction == "none"


def test_bundle_rejects_missing_screenshot() -> None:
    with pytest.raises(ValueError, match="screenshot"):
        FrontendReviewBundle.from_payload(
            {"schema_version": "1", "source": "upload", "prompt": "Review"}
        )


def test_vision_result_accepts_fenced_json_and_clamps_confidence() -> None:
    result = parse_vision_result(
        "```json\n"
        '{"summary":"bad CTA","findings":[{"id":"f1",'
        '"severity":"high","category":"layout","problem":"below fold",'
        '"confidence":1.8}]}'
        "\n```"
    )

    assert result.findings[0].finding_id == "f1"
    assert result.findings[0].confidence == 1.0


@pytest.mark.parametrize("missing", ["id", "problem", "confidence"])
def test_vision_result_rejects_missing_required_finding_fields(missing: str) -> None:
    finding = {
        "id": "f1",
        "severity": "high",
        "category": "layout",
        "problem": "below fold",
        "confidence": 0.5,
    }
    del finding[missing]

    result = parse_vision_result('{"summary":"bad","findings":[' + str(finding).replace("'", '"') + "]}")

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


def test_vision_result_clamps_confidence_at_zero() -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        '"category":"layout","problem":"bad","confidence":-0.5}]}'
    )

    assert result.findings[0].confidence == 0.0


@pytest.mark.parametrize("confidence", ["NaN", "Infinity", "-Infinity"])
def test_vision_result_rejects_non_finite_confidence(confidence: str) -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        + '"category":"layout","problem":"bad","confidence":' + confidence + "}]}"
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


def test_vision_result_rejects_non_finite_bbox_coordinates() -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        '"category":"layout","problem":"bad","confidence":0.5,'
        '"bbox":[0, 1, 2, Infinity]}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


@pytest.mark.parametrize("field", ["unknowns", "recommended_checks"])
def test_vision_result_rejects_malformed_optional_lists(field: str) -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[],"' + field + '":"not-a-list"}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


def test_successful_vision_result_has_non_terminal_invariants() -> None:
    result = parse_vision_result(
        '{"schema_version":"1","summary":"ok","findings":[],'
        '"unknowns":["no DOM"],"recommended_checks":["run tests"]}'
    )

    assert result.terminal is False
    assert result.error == {}
    assert result.findings == ()
    assert result.unknowns == ("no DOM",)
    assert result.recommended_checks == ("run tests",)


@pytest.mark.parametrize("field", ["element_ids", "evidence"])
def test_vision_result_rejects_string_sequence_fields(field: str) -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        '"category":"layout","problem":"bad","confidence":0.5,"'
        + field
        + '":"not-a-list"}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


def test_vision_result_rejects_unknown_severity() -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"urgent",'
        '"category":"layout","problem":"bad","confidence":0.5}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert "severity" in result.error["message"]


def test_vision_result_rejects_unknown_category_as_terminal_failure() -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"high",'
        '"category":"content", "problem":"bad","confidence":0.5}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert "category" in result.error["message"]


def test_malformed_vision_result_is_terminal_structured_failure() -> None:
    result = parse_vision_result("not JSON")

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


def test_coder_packet_keeps_referenced_dom_ancestors_and_bounded_runtime() -> None:
    packet = build_coder_packet(
        prompt="Fix mobile checkout",
        findings=[{"id": "f1", "element_ids": ["el-42"]}],
        dom={
            "elements": [
                {"element_id": "root", "ancestor_ids": []},
                {"element_id": "parent", "ancestor_ids": ["root"]},
                {"element_id": "el-42", "ancestor_ids": ["root", "parent"]},
                {"element_id": "other", "ancestor_ids": ["root"]},
            ]
        },
        repo_context={"files": ["src/Checkout.tsx"]},
        runtime_context={"console": ["error"] * 100, "network": ["failed"] * 100},
        max_runtime_items=2,
    )

    assert [element["element_id"] for element in packet["dom"]["elements"]] == [
        "root",
        "parent",
        "el-42",
    ]
    assert packet["runtime"]["console"] == ["error", "error"]
    assert packet["repo"] == {"files": ["src/Checkout.tsx"]}


def test_coder_packet_bounds_runtime_dict_keys_and_nested_lists() -> None:
    packet = build_coder_packet(
        prompt="Review runtime",
        findings=[],
        dom={"elements": []},
        runtime_context={
            "console": ["one", "two", "three"],
            "network": ["one", "two", "three"],
            "extra": ["must be omitted"],
        },
        max_runtime_items=2,
    )

    assert list(packet["runtime"]) == ["console", "network"]
    assert packet["runtime"]["console"] == ["one", "two"]


def test_coder_packet_normalizes_negative_runtime_bound() -> None:
    packet = build_coder_packet(
        prompt="Review runtime",
        findings=[],
        dom={"elements": []},
        runtime_context={"console": ["error"]},
        max_runtime_items=-1,
    )

    assert packet["runtime"] == {}


@pytest.mark.parametrize("dom", [{"elements": [None]}, {"elements": "not-a-list"}])
def test_coder_packet_reports_malformed_dom_as_terminal_failure(dom: dict) -> None:
    packet = build_coder_packet(prompt="Review DOM", findings=[], dom=dom)

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "malformed_coder_context"


def test_coder_packet_reports_none_findings_as_terminal_failure() -> None:
    packet = build_coder_packet(prompt="Review", findings=None, dom={"elements": []})

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "malformed_coder_context"


@pytest.mark.parametrize("runtime_context", [[], "", 0])
def test_coder_packet_reports_falsey_non_mapping_runtime_as_terminal_failure(
    runtime_context: object,
) -> None:
    packet = build_coder_packet(
        prompt="Review runtime",
        findings=[],
        dom={"elements": []},
        runtime_context=runtime_context,
    )

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "malformed_coder_context"
