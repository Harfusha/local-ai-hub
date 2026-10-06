from __future__ import annotations

from local_ai_hub.mcp_server import _quality_check_semantic_result
from local_ai_hub.services import LocalAIServices


def _assert_unverified_advisory(result: dict) -> None:
    assert result["success"] is True
    assert result["advisory_only"] is True
    assert result["semantic_quality"]["usable"] is False
    assert result["bypass_reason"] == "unrelated_output"
    assert "requires verification" in result["quality_warning"]
    assert result.get("verified") is not True


def test_service_keeps_unrelated_model_output_advisory_even_when_call_succeeded() -> None:
    result = LocalAIServices._apply_semantic_quality(
        {"success": True, "text": "Fix src/Calculator.java"},
        task="diagnose src/auth.py",
        evidence_paths=["src/auth.py"],
    )

    _assert_unverified_advisory(result)


def test_mcp_boundary_keeps_unrelated_model_output_advisory_even_when_call_succeeded() -> None:
    result = _quality_check_semantic_result(
        {"success": True, "text": "Fix src/Calculator.java"},
        task="diagnose src/auth.py",
        context="src/auth.py",
        changed_paths=["src/auth.py"],
    )

    _assert_unverified_advisory(result)
