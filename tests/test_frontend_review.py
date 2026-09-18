from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.frontend_review import (
    build_model_context,
    FrontendReviewError,
    project_live_dom,
)
from local_ai_hub.services import LocalAIServices


def test_build_model_context_includes_screenshot_dom_and_prompt() -> None:
    context = build_model_context(
        prompt="Why is the button missing?",
        screenshot_data_url="data:image/png;base64,AA==",
        dom={
            "redaction": "none",
            "elements": [{"element_id": "el-1", "tag": "button"}],
        },
        accessibility={"el-1": {"role": "button"}},
        computed_styles={"el-1": {"display": "none"}},
        viewport={"width": 390, "height": 844},
    )

    assert context.prompt == "Why is the button missing?"
    assert context.screenshot_data_url.endswith("AA==")
    assert context.dom["elements"][0]["element_id"] == "el-1"
    assert context.accessibility["el-1"]["role"] == "button"


def test_full_dom_is_not_semantically_redacted() -> None:
    projected = project_live_dom(
        {
            "redaction": "none",
            "html": "<main>user@example.test</main>",
            "elements": [{"element_id": "root", "tag": "main"}],
        },
        max_chars=10_000,
    )

    assert "user@example.test" in projected["html"]


def test_dom_limit_is_terminal_not_truncated() -> None:
    projected = project_live_dom(
        {
            "redaction": "none",
            "html": "x" * 20,
            "elements": [{"element_id": "root"}],
        },
        max_chars=10,
    )

    assert projected["terminal"] is True
    assert projected["error"]["code"] == "frontend_context_too_large"


def test_dom_requires_explicit_none_redaction_marker() -> None:
    projected = project_live_dom(
        {"html": "<main />", "elements": [{"element_id": "root"}]},
        max_chars=10_000,
    )

    assert projected["terminal"] is True
    assert projected["error"]["code"] == "missing_dom_redaction"


def test_dom_rejects_oversized_element_content() -> None:
    projected = project_live_dom(
        {
            "redaction": "none",
            "elements": [{"element_id": "root", "text": "x" * 2_001}],
        },
        max_chars=10_000,
    )

    assert projected["terminal"] is True
    assert projected["error"]["code"] == "frontend_context_too_large"


def test_model_context_rejects_nested_a11y_overflow() -> None:
    try:
        build_model_context(
            prompt="Review",
            screenshot_data_url="data:image/png;base64,AA==",
            dom={"redaction": "none", "elements": [{"element_id": "root"}]},
            accessibility={"root": {"name": "x" * 2_001}},
            computed_styles={},
            viewport={},
        )
    except Exception as exc:
        assert getattr(exc, "code", "") == "frontend_context_too_large"
    else:
        raise AssertionError("oversized accessibility context must be terminal")


def test_model_context_rejects_excessive_nesting() -> None:
    nested = value = {}
    for _ in range(10):
        value["next"] = {}
        value = value["next"]

    try:
        build_model_context(
            prompt="Review",
            screenshot_data_url="data:image/png;base64,AA==",
            dom={"redaction": "none", "elements": [{"element_id": "root"}]},
            accessibility={},
            computed_styles={},
            viewport={},
            runtime=nested,
        )
    except Exception as exc:
        assert getattr(exc, "code", "") == "frontend_context_too_deep"
    else:
        raise AssertionError("deep runtime context must be terminal")


def test_inline_json_size_is_rejected_before_json_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = json.dumps({"runtime": "x" * 12_000})
    original_loads = json.loads

    def fail_if_called(value: object, *args: object, **kwargs: object) -> object:
        if value is raw:
            raise AssertionError("oversized inline JSON reached json.loads")
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", fail_if_called)
    with pytest.raises(FrontendReviewError) as raised:
        build_model_context(
            prompt="Review",
            screenshot_data_url="data:image/png;base64,AA==",
            dom={"redaction": "none", "elements": [{"element_id": "root"}]},
            accessibility={},
            computed_styles={},
            viewport={},
            runtime=raw,
        )

    assert raised.value.code == "frontend_context_too_large"


def test_deep_inline_json_is_rejected_before_recursion(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = '{"next":' * 32 + "{}" + "}" * 32

    def fail_with_recursion(value: object, *args: object, **kwargs: object) -> object:
        if value == raw:
            raise RecursionError("simulated parser recursion")
        return json.loads(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", fail_with_recursion)
    with pytest.raises(FrontendReviewError) as raised:
        build_model_context(
            prompt="Review",
            screenshot_data_url="data:image/png;base64,AA==",
            dom={"redaction": "none", "elements": [{"element_id": "root"}]},
            accessibility={},
            computed_styles={},
            viewport={},
            runtime=raw,
        )

    assert raised.value.code == "frontend_context_too_deep"


def test_project_live_dom_rejects_duplicate_element_ids() -> None:
    projected = project_live_dom(
        {
            "redaction": "none",
            "html": "<button>Save</button>",
            "elements": [
                {"element_id": "el-1", "tag": "button"},
                {"element_id": "el-1", "tag": "button"},
            ],
        },
        max_chars=10_000,
    )

    assert projected["terminal"] is True
    assert projected["error"]["code"] == "duplicate_dom_element_id"


def test_html_dom_requires_stable_elements_list() -> None:
    projected = project_live_dom(
        {"redaction": "none", "html": "<main />"}, max_chars=10_000
    )

    assert projected["terminal"] is True
    assert projected["error"]["code"] == "missing_dom_elements"


def test_dom_rejects_semantic_redaction_without_silent_projection() -> None:
    projected = project_live_dom(
        {
            "redaction": "semantic",
            "html": "<main>secret</main>",
            "elements": [{"element_id": "root"}],
        },
        max_chars=10_000,
    )

    assert projected["terminal"] is True
    assert projected["error"]["code"] == "semantic_dom_redaction_not_allowed"


def test_service_passes_screenshot_and_dom_bundle_to_vision_model(tmp_path: Path) -> None:
    runtime = MagicMock()
    runtime.request.side_effect = [
        {"capabilities": ["vision"]},
        {
            "response": json.dumps(
                {
                    "summary": "Hidden CTA",
                    "findings": [
                        {
                            "id": "f-1",
                            "severity": "high",
                            "category": "layout",
                            "problem": "CTA is hidden",
                            "observed": "computed display is none",
                            "hypothesized": "hydration rule hides CTA",
                            "uncertainty": ["runtime visibility after hydration"],
                            "confidence": 0.91,
                            "element_ids": ["el-1"],
                            "evidence": ["display:none"],
                        }
                    ],
                    "unknowns": ["runtime visibility after hydration"],
                }
            )
        },
    ]
    artifacts = MagicMock()
    artifacts.get_binary.return_value = {
        "success": True,
        "mime_type": "image/png",
        "data_base64": "ZmFrZQ==",
        "size_bytes": 4,
    }
    artifacts.get.side_effect = [
        {
            "success": True,
            "text": json.dumps(
                {
            "redaction": "none",
            "html": "<button id='save'>Save</button>",
                    "elements": [
                        {"element_id": "el-1", "tag": "button", "ancestor_ids": []}
                    ],
                }
            ),
            "next_offset": None,
        },
        {
            "success": True,
            "text": json.dumps({"el-1": {"role": "button"}}),
            "next_offset": None,
        },
        {
            "success": True,
            "text": json.dumps({"el-1": {"display": "none"}}),
            "next_offset": None,
        },
    ]
    services = LocalAIServices(
        config={"models": {"vision": "qwen3-vl:4b"}, "server": {"state_dir": str(tmp_path)}},
        runtime=runtime,
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=artifacts,
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )

    result = services.vision(
        {
            "image_artifact_id": "img-1",
            "dom_artifact_id": "dom-1",
            "accessibility_artifact_id": "a11y-1",
            "computed_styles_artifact_id": "styles-1",
            "prompt": "Review CTA and tell coder how to fix it",
        },
        "tenant-a",
    )

    assert result["success"] is True
    assert result["review"]["findings"][0]["element_ids"] == ("el-1",)
    assert result["review"]["unknowns"] == ("runtime visibility after hydration",)
    payload = runtime.request.call_args_list[-1].args[1]
    assert payload["images"] == ["ZmFrZQ=="]
    assert "<button id='save'>Save</button>" in payload["prompt"]
    assert "el-1" in payload["prompt"]
    assert result["coder_context"]["artifact_refs"]["dom"] == "dom-1"
    assert "untrusted evidence" in payload["prompt"].lower()


def test_service_rejects_missing_or_oversized_dom_refs(tmp_path: Path) -> None:
    runtime = MagicMock()
    artifacts = MagicMock()
    artifacts.get_binary.return_value = {
        "success": True,
        "mime_type": "image/png",
        "data_base64": "ZmFrZQ==",
        "size_bytes": 4,
    }
    artifacts.get.return_value = {
        "success": True,
        "text": "x" * 12_001,
        "total_chars": 12_001,
        "next_offset": None,
    }
    services = LocalAIServices(
        config={"models": {"vision": "qwen3-vl:4b"}, "server": {"state_dir": str(tmp_path)}},
        runtime=runtime,
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=artifacts,
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )

    result = services.vision(
        {"image_artifact_id": "img-1", "dom_artifact_id": "dom-too-large"},
        "tenant-a",
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["error_code"] == "vision_artifact_too_large"
    assert runtime.request.call_count == 0


def test_service_rejects_malformed_frontend_bundle(tmp_path: Path) -> None:
    runtime = MagicMock()
    artifacts = MagicMock()
    artifacts.get_binary.return_value = {
        "success": True,
        "mime_type": "image/png",
        "data_base64": "ZmFrZQ==",
        "size_bytes": 4,
    }
    artifacts.get.return_value = {
        "success": True,
        "text": "{not-json",
        "next_offset": None,
    }
    services = LocalAIServices(
        config={"models": {"vision": "qwen3-vl:4b"}, "server": {"state_dir": str(tmp_path)}},
        runtime=runtime,
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=artifacts,
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )

    result = services.vision(
        {"image_artifact_id": "img-1", "bundle_artifact_id": "bundle-bad"},
        "tenant-a",
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["error_code"] == "vision_bundle_invalid"
