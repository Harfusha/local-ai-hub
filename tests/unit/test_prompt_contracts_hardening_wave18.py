import pytest
from local_ai_hub.prompt_contracts import (
    _clip,
    _lines,
    can_model_perform,
    cannot_model_perform,
    is_operation_supported,
    capability_for,
    build_prompt,
)


def test_clip_and_lines_hardening():
    # _clip with booleans or invalid limits
    assert _clip(True, 100) == ""
    assert _clip(False, 100) == ""
    assert _clip("hello", True) == ""
    assert _clip("hello", -5) == ""
    assert _clip("hello\x00world", 100) == "helloworld"

    # _lines with booleans or non-sequence
    assert _lines(True) == "- none supplied"
    assert _lines(False) == "- none supplied"
    assert _lines([True, False, None, ""]) == "- none supplied"
    assert _lines([True, "valid line", False, "another\x00line"]) == "- valid line\n- anotherline"
    assert _lines(["test"], limit=True) == "- none supplied"


def test_model_perform_and_capabilities_hardening():
    assert not can_model_perform(True, "delegate")
    assert not can_model_perform("qwen2.5-coder:7b", True)
    assert not can_model_perform(123, 456)

    assert cannot_model_perform(True, "apply_changes")
    assert cannot_model_perform("qwen2.5-coder:7b", True)
    assert cannot_model_perform(123, 456)

    assert not is_operation_supported(True)
    assert not is_operation_supported(False)
    assert not is_operation_supported(123)

    cap = capability_for(True, role=False)
    assert cap.model == "" or cap.tier == "background"

    malformed_model = capability_for("qwen2.5-coder:7\x00b")
    assert malformed_model.model == "qwen2.5-coder:0.5b"
    assert "root_cause" not in malformed_model.can


def test_build_prompt_hardening():
    pkg = build_prompt(
        operation="delegate",
        model="qwen2.5-coder:7b",
        task="do something",
        acceptance_criteria=[True, "criterion 1"],
        evidence_ids=[False, "ev-1"],
        changed_paths=[True, "path/one.py"],
    )
    assert "True" not in pkg.user
    assert "False" not in pkg.user
    assert "criterion 1" in pkg.user
    assert "ev-1" in pkg.user
    assert "path/one.py" in pkg.user
