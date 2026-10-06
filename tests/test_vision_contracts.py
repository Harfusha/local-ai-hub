import json
from dataclasses import asdict

import pytest

from local_ai_hub.vision_contracts import (
    FrontendReviewBundle,
    build_coder_packet,
    image_dimensions,
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


def test_image_dimensions_read_png_and_jpeg_headers() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (640).to_bytes(4, "big") + (360).to_bytes(4, "big")
    jpeg = (
        b"\xff\xd8\xff\xc0\x00\x11\x08"
        + (360).to_bytes(2, "big")
        + (640).to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )

    assert image_dimensions(png) == (640, 360)
    assert image_dimensions(jpeg) == (640, 360)
    assert image_dimensions(b"unsupported") is None


@pytest.mark.parametrize("redaction", ["content", "semantic", "pii", ""])
def test_bundle_rejects_semantic_dom_redaction(redaction: str) -> None:
    with pytest.raises(ValueError, match="redaction"):
        FrontendReviewBundle.from_payload(
            {
                "screenshot": {"artifact_id": "art_img", "mime_type": "image/png"},
                "dom": {"redaction": redaction},
            }
        )


def test_bundle_rejects_missing_dom_redaction_marker() -> None:
    with pytest.raises(ValueError, match="redaction"):
        FrontendReviewBundle.from_payload(
            {
                "screenshot": {"artifact_id": "art_img", "mime_type": "image/png"},
                "dom": {"artifact_id": "art_dom"},
            }
        )


def test_bundle_rejects_oversized_inline_prompt() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        FrontendReviewBundle.from_payload(
            {
                "prompt": "x" * 2_001,
                "screenshot": {"artifact_id": "art_img", "mime_type": "image/png"},
            }
        )


def test_bundle_forwards_network_runtime_artifact_id() -> None:
    bundle = FrontendReviewBundle.from_payload(
        {
            "screenshot": {"artifact_id": "art_img", "mime_type": "image/png"},
            "runtime": {
                "console_artifact_id": "console-1",
                "network_artifact_id": "network-1",
            },
        }
    )

    assert bundle.runtime_artifact_id == "console-1"
    assert bundle.network_artifact_id == "network-1"


def test_vision_result_rejects_confidence_outside_contract() -> None:
    result = parse_vision_result(
        "```json\n"
        '{"summary":"bad CTA","findings":[{"id":"f1",'
        '"severity":"high","category":"layout","problem":"below fold",'
        '"confidence":1.8,"evidence":["CTA is below the visible fold"]}]}'
        "\n```"
    )

    assert result.terminal is True
    assert "confidence" in result.error["message"]


def test_grounded_vision_rejects_dom_ids_absent_from_supplied_dom() -> None:
    result = parse_vision_result(
        '{"summary":"button issue","findings":[{"id":"f1",'
        '"severity":"high","category":"interaction","problem":"button missing",'
        '"confidence":0.7,"element_ids":["submit-button"],'
        '"bbox":[1,1,10,10],"evidence":["<button>Submit</button>"]}]}',
        valid_element_ids=set(),
        image_size=(640, 360),
    )

    assert result.terminal is True
    assert "element_ids" in result.error["message"]


def test_grounded_vision_rejects_observation_fact_with_value_absent_from_dom() -> None:
    result = parse_vision_result(
        '{"summary":"button issue","findings":[{"id":"f1",'
        '"severity":"high","category":"interaction",'
        '"problem":"button label is wrong",'
        '"observed":"button text appears consistent",'
        '"hypothesized":"the label may be stale",'
        '"uncertainty":[],"confidence":0.7,'
        '"element_ids":["button-1"],"bbox":null,"evidence":["button-1"],'
        '"observation_facts":[{"source":"dom","element_id":"button-1",'
        '"field":"text","value":"Continue"}]}]}',
        require_observation_fields=True,
        valid_element_ids={"button-1"},
        observation_sources={"dom": {"button-1": {"text": "Cancel", "tag": "button"}}},
        image_size=(640, 360),
    )

    assert result.terminal is True
    assert "value does not match" in result.error["message"]


def test_grounded_vision_accepts_observation_fact_matching_cited_dom() -> None:
    observation_sources = {
        "dom": {"button-1": {"text": "Continue", "tag": "button"}}
    }
    result = parse_vision_result(
        '{"summary":"button issue","findings":[{"id":"f1",'
        '"severity":"high","category":"interaction",'
        '"problem":"button label is clear",'
        '"observed":"button text is Continue",'
        '"hypothesized":"label matches expected action",'
        '"uncertainty":[],"confidence":0.7,'
        '"element_ids":["button-1"],"bbox":null,"evidence":["button-1"],'
        '"observation_facts":[{"source":"dom","element_id":"button-1",'
        '"field":"text","value":"Continue"}]}]}',
        require_observation_fields=True,
        valid_element_ids={"button-1"},
        observation_sources=observation_sources,
        image_size=(640, 360),
    )

    assert result.terminal is False
    assert result.observation_sources == observation_sources
    assert result.findings[0].evidence == ("dom:button-1",)
    assert result.findings[0].observation_facts[0].value == "Continue"


def test_grounded_vision_rejects_problem_contradicted_by_observation_fact() -> None:
    result = parse_vision_result(
        '{"summary":"button mismatch","findings":[{"id":"f1",'
        '"severity":"low","category":"interaction",'
        '"problem":"Button text does not match the expected value of \'Continue\'.",'
        '"observed":"The exact button text is \'Continue\'.",'
        '"hypothesized":"The label may be incorrect.","uncertainty":[],"confidence":0.7,'
        '"element_ids":["button-1"],"bbox":null,"evidence":["button-1"],'
        '"observation_facts":[{"source":"dom","element_id":"button-1",'
        '"field":"text","value":"Continue"}]}]}',
        require_observation_fields=True,
        valid_element_ids={"button-1"},
        observation_sources={"dom": {"button-1": {"text": "Continue"}}},
        image_size=(800, 450),
    )

    assert result.terminal is True
    assert "problem contradicts supplied observation fact" in result.error["message"]


def test_grounded_vision_accepts_explicit_mismatch_against_different_dom_value() -> None:
    result = parse_vision_result(
        '{"summary":"button mismatch","findings":[{"id":"f1",'
        '"severity":"low","category":"interaction",'
        '"problem":"Button text does not match the expected value of \'Continue\'.",'
        '"observed":"The exact button text is \'Cancel\'.",'
        '"hypothesized":"The label may be incorrect.","uncertainty":[],"confidence":0.7,'
        '"element_ids":["button-1"],"bbox":null,"evidence":["button-1"],'
        '"observation_facts":[{"source":"dom","element_id":"button-1",'
        '"field":"text","value":"Cancel"}]}]}',
        require_observation_fields=True,
        valid_element_ids={"button-1"},
        observation_sources={"dom": {"button-1": {"text": "Cancel"}}},
        image_size=(800, 450),
    )

    assert result.terminal is False
    assert result.findings[0].observation_facts[0].value == "Cancel"


def test_grounded_vision_requires_observation_fact_for_dom_finding() -> None:
    result = parse_vision_result(
        '{"summary":"button issue","findings":[{"id":"f1",'
        '"severity":"high","category":"interaction",'
        '"problem":"button label is clear",'
        '"observed":"button text is Continue",'
        '"hypothesized":"label matches expected action",'
        '"uncertainty":[],"confidence":0.7,'
        '"element_ids":["button-1"],"bbox":null,"evidence":["button-1"]}]}',
        require_observation_fields=True,
        valid_element_ids={"button-1"},
        observation_sources={"dom": {"button-1": {"text": "Continue"}}},
        image_size=(640, 360),
    )

    assert result.terminal is True
    assert "observation_facts" in result.error["message"]


def test_grounded_vision_rejects_bbox_outside_supplied_image() -> None:
    result = parse_vision_result(
        '{"summary":"button issue","findings":[{"id":"f1",'
        '"severity":"high","category":"interaction","problem":"button issue",'
        '"confidence":0.7,"bbox":[489,316,652,360],'
        '"evidence":["image region"]}]}',
        valid_element_ids=set(),
        image_size=(640, 360),
    )

    assert result.terminal is True
    assert "bbox" in result.error["message"]


def test_grounded_image_only_finding_requires_valid_region_anchor() -> None:
    result = parse_vision_result(
        '{"summary":"button issue","findings":[{"id":"f1",'
        '"severity":"medium","category":"interaction","problem":"low contrast",'
        '"confidence":0.7,"bbox":[10,20,80,50],"evidence":["image region"]}]}',
        valid_element_ids=set(),
        image_size=(640, 360),
    )

    assert result.terminal is False
    assert result.findings[0].bbox == (10.0, 20.0, 80.0, 50.0)
    assert result.findings[0].evidence == ("image:0:10,20,80,50",)


def test_grounded_image_only_finding_rejects_dom_markup_as_evidence() -> None:
    result = parse_vision_result(
        '{"summary":"button issue","findings":[{"id":"f1",'
        '"severity":"medium","category":"interaction","problem":"submit control",'
        '"confidence":0.7,"bbox":[10,20,80,50],'
        '"evidence":["<button>Submit</button>"]}]}',
        valid_element_ids=set(),
        image_size=(640, 360),
    )

    assert result.terminal is True
    assert "DOM evidence" in result.error["message"]


def test_grounded_vision_accepts_ids_from_supplied_dom() -> None:
    result = parse_vision_result(
        '{"summary":"button issue","findings":[{"id":"f1",'
        '"severity":"medium","category":"interaction","problem":"button label unclear",'
        '"confidence":0.7,"element_ids":["button-1"],'
        '"evidence":["<button id=button-1>Continue</button>"]}]}',
        valid_element_ids={"button-1"},
    )

    assert result.terminal is False
    assert result.findings[0].element_ids == ("button-1",)
    assert result.findings[0].evidence == ("dom:button-1",)


def test_vision_result_rejects_empty_findings_without_summary() -> None:
    result = parse_vision_result('{"findings":[]}')

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert "summary" in result.error["message"]


def test_vision_result_rejects_whitespace_summary_with_findings() -> None:
    result = parse_vision_result(
        '{"summary":"  ","findings":[{"id":"f1",'
        '"severity":"medium","category":"layout","problem":"overlap",'
        '"confidence":0.7,"evidence":["visible overlap"]}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert "summary" in result.error["message"]


def test_vision_result_rejects_findings_without_image_or_dom_evidence() -> None:
    result = parse_vision_result(
        '{"summary":"bad CTA","findings":[{"id":"f1",'
        '"severity":"high","category":"layout","problem":"below fold",'
        '"confidence":0.8,"evidence":[]}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert "evidence" in result.error["message"]


def test_dom_vision_result_preserves_observation_hypothesis_uncertainty() -> None:
    result = parse_vision_result(
        '{"summary":"CTA is hidden.","findings":[{"id":"f1","severity":"high","category":"layout",'
        '"problem":"CTA hidden","observed":"display is none",'
        '"hypothesized":"hydration rule hides CTA",'
        '"uncertainty":["runtime state not captured"],"confidence":0.8,'
        '"evidence":["computed style"]}]}',
        require_observation_fields=True,
    )

    assert result.terminal is False
    finding = result.findings[0]
    assert finding.observed == "display is none"
    assert finding.hypothesized == "hydration rule hides CTA"
    assert finding.uncertainty == ("runtime state not captured",)
    assert finding.evidence == ("computed style",)


@pytest.mark.parametrize("missing", ["observed", "hypothesized", "uncertainty"])
def test_dom_vision_result_rejects_missing_observation_contract(missing: str) -> None:
    finding = {
        "id": "f1",
        "severity": "high",
        "category": "layout",
        "problem": "CTA hidden",
        "observed": "display is none",
        "hypothesized": "hydration rule hides CTA",
        "uncertainty": ["runtime state not captured"],
        "confidence": 0.8,
        "evidence": ["computed style"],
    }
    del finding[missing]

    result = parse_vision_result(
        '{"findings":[' + str(finding).replace("'", '"') + "]}",
        require_observation_fields=True,
    )

    assert result.terminal is True
    assert missing in result.error["message"]


@pytest.mark.parametrize("field", ["observed", "hypothesized"])
def test_dom_vision_result_rejects_non_string_observation_fields(field: str) -> None:
    result = parse_vision_result(
        '{\"findings\":[{\"id\":\"f1\",\"severity\":\"high\",\"category\":\"layout\",'
        '\"problem\":\"CTA hidden\",\"observed\":\"display is none\",'
        '\"hypothesized\":\"hydration rule hides CTA\",'
        '\"uncertainty\":[],\"confidence\":0.8,'
        '\"' + field + '\":42}]}',
        require_observation_fields=True,
    )

    assert result.terminal is True
    assert field in result.error["message"]


@pytest.mark.parametrize("field", ["observed", "hypothesized"])
def test_dom_vision_result_rejects_whitespace_only_observation_fields(
    field: str,
) -> None:
    result = parse_vision_result(
        '{"findings":[{"id":"f1","severity":"high","category":"layout",'
        '"problem":"CTA hidden","observed":"display is none",'
        '"hypothesized":"hydration rule hides CTA",'
        '"uncertainty":[],"confidence":0.8,'
        '"' + field + '":"  \\t "}]}',
        require_observation_fields=True,
    )

    assert result.terminal is True
    assert f"{field} must be a non-empty string" in result.error["message"]


@pytest.mark.parametrize("missing", ["id", "problem", "confidence"])
def test_vision_result_rejects_missing_required_finding_fields(missing: str) -> None:
    finding = {
        "id": "f1",
        "severity": "high",
        "category": "layout",
        "problem": "below fold",
        "confidence": 0.5,
        "evidence": ["CTA appears below the visible fold"],
    }
    del finding[missing]

    result = parse_vision_result('{"summary":"bad","findings":[' + str(finding).replace("'", '"') + "]}")

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


def test_vision_result_rejects_confidence_below_zero() -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        '"category":"layout","problem":"bad","confidence":-0.5,'
        '"evidence":["visible layout issue"]}]}'
    )

    assert result.terminal is True
    assert "confidence" in result.error["message"]


@pytest.mark.parametrize("confidence", ["NaN", "Infinity", "-Infinity"])
def test_vision_result_rejects_non_finite_confidence(confidence: str) -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        + '"category":"layout","problem":"bad","confidence":' + confidence + "}]}"
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


@pytest.mark.parametrize("confidence", ['"0.8"', "true"])
def test_vision_result_rejects_non_numeric_confidence(confidence: str) -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        '"category":"layout","problem":"bad","confidence":' + confidence +
        ',"evidence":["visible layout issue"]}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert "confidence" in result.error["message"]


@pytest.mark.parametrize(("field", "value"), [("id", 4), ("problem", 404)])
def test_vision_result_rejects_non_string_required_text(
    field: str, value: int
) -> None:
    finding = {
        "id": "f1",
        "severity": "low",
        "category": "layout",
        "problem": "bad",
        "confidence": 0.5,
        "evidence": ["visible layout issue"],
    }
    finding[field] = value
    result = parse_vision_result(json.dumps({"summary": "review", "findings": [finding]}))

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert field in result.error["message"]


@pytest.mark.parametrize("coordinate", ['"0.25"', "true"])
def test_vision_result_requires_numeric_bbox_coordinates(coordinate: str) -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        '"category":"layout","problem":"bad","confidence":0.5,'
        '"evidence":["visible layout issue"],"bbox":[' + coordinate + ',0.1,0.2,0.3]}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert "bbox coordinates" in result.error["message"]


def test_vision_result_rejects_non_finite_bbox_coordinates() -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"low",'
        '"category":"layout","problem":"bad","confidence":0.5,'
        '"bbox":[0, 1, 2, Infinity]}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"


def test_vision_result_bounds_bbox_to_image_dimensions() -> None:
    raw = json.dumps({
        "summary": "bounded region",
        "findings": [{
            "id": "f1", "severity": "low", "category": "layout",
            "problem": "issue", "confidence": 0.5,
            "bbox": [90, 80, 20, 30], "evidence": ["visible region"],
        }],
    })

    result = parse_vision_result(raw, image_size=(100, 100))

    assert result.terminal is True
    assert "image dimensions" in result.error["message"]


def test_image_dimensions_reads_png_header() -> None:
    header = bytearray(24)
    header[:8] = b"\x89PNG\r\n\x1a\n"
    header[16:20] = (640).to_bytes(4, "big")
    header[20:24] = (480).to_bytes(4, "big")

    assert image_dimensions(bytes(header)) == (640, 480)


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        (b"GIF89a" + (320).to_bytes(2, "little") + (240).to_bytes(2, "little"), (320, 240)),
        (
            b"RIFF" + b"\x00\x00\x00\x00" + b"WEBPVP8X"
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00"
            + (319).to_bytes(3, "little") + (239).to_bytes(3, "little"),
            (320, 240),
        ),
    ],
)
def test_image_dimensions_reads_gif_and_webp_headers(
    image: bytes, expected: tuple[int, int]
) -> None:
    assert image_dimensions(image) == expected


def test_dom_facts_must_ground_every_cited_element() -> None:
    raw = json.dumps({
        "summary": "two controls",
        "findings": [{
            "id": "f1", "severity": "low", "category": "accessibility",
            "problem": "controls", "confidence": 0.5,
            "element_ids": ["a", "b"],
            "observation_facts": [
                {"source": "dom", "element_id": "a", "field": "text", "value": "A"}
            ],
            "evidence": ["DOM controls, including A"],
        }],
    })

    result = parse_vision_result(
        raw,
        valid_element_ids={"a", "b"},
        observation_sources={"dom": {"a": {"text": "A"}, "b": {"text": "B"}}},
    )

    assert result.terminal is True
    assert "every cited DOM element" in result.error["message"]


def test_dom_fact_must_support_observed_text() -> None:
    raw = json.dumps({
        "summary": "button label",
        "findings": [{
            "id": "f1", "severity": "low", "category": "accessibility",
            "problem": "button label", "observed": "button is disabled",
            "confidence": 0.5, "element_ids": ["a"],
            "observation_facts": [
                {"source": "dom", "element_id": "a", "field": "text", "value": "Submit"}
            ],
            "evidence": ["DOM fact for a"],
        }],
    })

    result = parse_vision_result(
        raw,
        valid_element_ids={"a"},
        observation_sources={"dom": {"a": {"text": "Submit"}}},
    )

    assert result.terminal is True
    assert "support" in result.error["message"]


def test_visible_angle_bracket_text_is_not_treated_as_dom_markup() -> None:
    result = parse_vision_result(json.dumps({
        "summary": "keyboard hint",
        "findings": [{
            "id": "f1", "severity": "info", "category": "accessibility",
            "problem": "keyboard hint", "confidence": 0.5,
            "evidence": ["The visible shortcut is <Enter>."],
        }],
    }))

    assert result.terminal is False


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
        '"category":"layout","problem":"bad","confidence":0.5,'
        '"evidence":["visible layout issue"]}]}'
    )

    assert result.terminal is True
    assert result.error["code"] == "malformed_vision_output"
    assert "severity" in result.error["message"]


def test_vision_result_rejects_unknown_category_as_terminal_failure() -> None:
    result = parse_vision_result(
        '{"summary":"bad","findings":[{"id":"f1","severity":"high",'
        '"category":"content", "problem":"bad","confidence":0.5,'
        '"evidence":["visible content issue"]}]}'
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
        runtime_context={"console": ["error", "error"], "network": ["failed", "failed"]},
        max_runtime_items=2,
    )

    assert [element["element_id"] for element in packet["dom"]["elements"]] == [
        "root",
        "parent",
        "el-42",
    ]
    assert packet["runtime"]["console"] == ["error", "error"]
    assert packet["repo"] == {"files": ["src/Checkout.tsx"]}


def test_coder_packet_bounds_finding_payloads() -> None:
    packet = build_coder_packet(
        prompt="Review",
        findings=[{"element_ids": ["cta"], "problem": "x" * 100_000}],
        dom={"elements": [{"element_id": "cta"}]},
    )

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "frontend_context_too_large"


def test_coder_packet_rejects_findings_that_reference_missing_dom_elements() -> None:
    packet = build_coder_packet(
        prompt="Review checkout",
        findings=[{"id": "f1", "element_ids": ["invented-button"]}],
        dom={"elements": [{"element_id": "real-button", "tag": "button"}]},
    )

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "malformed_coder_context"
    assert "invented-button" in packet["error"]["message"]


def test_coder_packet_bounds_runtime_dict_keys_and_nested_lists() -> None:
    packet = build_coder_packet(
        prompt="Review runtime",
        findings=[],
        dom={"elements": []},
        runtime_context={"console": ["one", "two"], "network": ["one", "two"]},
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

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "frontend_context_too_large"


def test_coder_packet_rejects_runtime_overflow_instead_of_truncating() -> None:
    packet = build_coder_packet(
        prompt="Review runtime",
        findings=[],
        dom={"elements": []},
        runtime_context={"network": ["one", "two", "three"]},
        max_runtime_items=2,
    )

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "frontend_context_too_large"


def test_coder_packet_rejects_oversized_prompt() -> None:
    packet = build_coder_packet(
        prompt="x" * 2_001,
        findings=[],
        dom={"elements": []},
    )

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "frontend_context_too_large"


@pytest.mark.parametrize("dom", [{"elements": [None]}, {"elements": "not-a-list"}])
def test_coder_packet_reports_malformed_dom_as_terminal_failure(dom: dict) -> None:
    packet = build_coder_packet(prompt="Review DOM", findings=[], dom=dom)

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "malformed_coder_context"


def test_coder_packet_reports_none_findings_as_terminal_failure() -> None:
    packet = build_coder_packet(prompt="Review", findings=None, dom={"elements": []})

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "malformed_coder_context"


def test_coder_packet_bounds_finding_payloads() -> None:
    packet = build_coder_packet(
        prompt="Review",
        findings=[{"element_ids": ["cta"], "problem": "x" * 100_000}],
        dom={"elements": [{"element_id": "cta"}]},
    )

    assert packet["terminal"] is True
    assert packet["error"]["code"] == "frontend_context_too_large"


def test_coder_packet_normalizes_parsed_finding_tuples() -> None:
    parsed = parse_vision_result(
        '{"summary":"button","findings":[{"id":"f1",'
        '"severity":"low","category":"layout",'
        '"problem":"visible issue","confidence":0.8,'
        '"uncertainty":["small sample"],"element_ids":[],'
        '"bbox":[1,2,3,4],"evidence":["button is visible"]}]}'
    )
    finding = asdict(parsed.findings[0])

    packet = build_coder_packet(prompt="Review", findings=[finding], dom={"elements": []})

    assert "terminal" not in packet
    assert packet["findings"][0]["uncertainty"] == ["small sample"]
    assert packet["findings"][0]["bbox"] == [1.0, 2.0, 3.0, 4.0]


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


def test_strict_vision_output_rejects_unknown_root_field() -> None:
    result = parse_vision_result(
        '{"summary":"No findings.","findings":[],"unknowns":[],'
        '"recommended_checks":[],"extra":"ignored"}',
        strict_output_shape=True,
    )

    assert result.terminal is True
    assert "required root fields" in result.error["message"]

@pytest.mark.parametrize(("observed", "fact", "terminal"), [
    ("The exact button text is 'Continue'.", "Continue", True),
    ("The exact button text is 'Cancel'.", "Cancel", False),
])
def test_grounded_vision_checks_explicit_expected_value_mismatch(
    observed: str, fact: str, terminal: bool,
) -> None:
    payload = {
        "summary": "button mismatch",
        "findings": [{
            "id": "f1",
            "severity": "low",
            "category": "interaction",
            "problem": "Button text does not match the expected value of 'Continue'.",
            "observed": observed,
            "hypothesized": "The label may be incorrect.",
            "uncertainty": [],
            "confidence": 0.7,
            "element_ids": ["button-1"],
            "bbox": None,
            "evidence": [f"DOM text: {fact}"],
            "observation_facts": [{
                "source": "dom",
                "element_id": "button-1",
                "field": "text",
                "value": fact,
            }],
        }],
    }

    result = parse_vision_result(
        json.dumps(payload),
        require_observation_fields=True,
        valid_element_ids={"button-1"},
        observation_sources={"dom": {"button-1": {"text": fact}}},
        image_size=(800, 450),
    )

    assert result.terminal is terminal
    if terminal:
        assert "problem contradicts supplied observation fact" in result.error["message"]
    else:
        assert result.findings[0].observation_facts[0].value == fact

def test_grounded_vision_rejects_live_output_missing_hypothesized() -> None:
    payload = {
        "summary": "button label review",
        "findings": [{
            "id": "f1",
            "severity": "low",
            "category": "interaction",
            "problem": "Button may show an incorrect label.",
            "observed": "Button text is Continue.",
            "uncertainty": [],
            "confidence": 0.7,
            "element_ids": ["button-1"],
            "bbox": None,
            "evidence": ["DOM text: Continue"],
            "observation_facts": [{
                "source": "dom",
                "element_id": "button-1",
                "field": "text",
                "value": "Continue",
            }],
        }],
    }

    result = parse_vision_result(
        json.dumps(payload),
        require_observation_fields=True,
        valid_element_ids={"button-1"},
        observation_sources={"dom": {"button-1": {"text": "Continue"}}},
        image_size=(800, 450),
    )

    assert result.terminal is True
    assert "hypothesized" in result.error["message"]
