from pathlib import Path

from local_ai_hub.generator import _semantic_handoff_contract
from local_ai_hub.routing import targeted_semantic_handoff


GUIDANCE = "For non-trivial edits, request evidence-grounded local test suggestions and review the diff"


def test_generated_guidance_has_actionable_local_workflow():
    text = _semantic_handoff_contract(None)
    assert GUIDANCE in text
    assert "unavailable" in text
    assert 'local_ai_task(action="review")' in text
    assert 'local_ai_task(action="delegate")' in text


def test_install_and_update_prompts_match_local_workflow():
    root = Path(__file__).resolve().parents[1]
    for name in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md"):
        text = (root / "docs" / name).read_text(encoding="utf-8")
        assert GUIDANCE in text
        assert "Only when the user explicitly requests closed delegation" in text


def test_prompts_describe_tool_capability_fallback():
    root = Path(__file__).resolve().parents[1]
    for name in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md", "MODEL_CAPABILITIES.md"):
        assert "Unknown tool capability uses an advisory response without tools" in (root / "docs" / name).read_text(encoding="utf-8")


def test_test_suggestion_hint_needs_actual_relevant_evidence_and_enabled_backend():
    result = {"success": True, "test_files": ["tests/test_example.py"]}
    hint = targeted_semantic_handoff("local_ai_repo", "affected_tests", result, True)
    assert hint["tool"] == "local_ai_task"
    assert hint["actions"] == ["delegate"]
    assert hint["required"] is False
    assert "test" in hint["purpose"].lower()
    assert targeted_semantic_handoff("local_ai_repo", "affected_tests", result, False) is None
    assert targeted_semantic_handoff("local_ai_repo", "affected_tests", {"success": True, "test_files": []}, True) is None
    assert targeted_semantic_handoff("local_ai_repo", "search", result, True) is None
    assert targeted_semantic_handoff("local_ai_repo", "affected_tests", {"success": False, "test_files": ["x"]}, True) is None


def test_test_impact_mcp_response_offers_targeted_handoff_by_default(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from local_ai_hub import mcp_server
    monkeypatch.setattr(mcp_server, "FEATURES", SimpleNamespace(tasks=True, status=True, has_any_model=lambda: True))
    monkeypatch.setattr(mcp_server, "configured_state_dir", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda path: object())
    monkeypatch.setattr(mcp_server, "_classify_mcp_operation", lambda *args: ("repo", False))
    monkeypatch.setattr(mcp_server, "operational_mode_gate_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "detailed_diagnostics_enabled", lambda cfg: False)
    monkeypatch.setattr(mcp_server, "diagnostic_mcp_operation", lambda *args: False)
    monkeypatch.setattr(mcp_server, "validate_operation_output", lambda *args: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **kwargs: None)

    @mcp_server._instrumented_tool()
    def local_ai_repo(action):
        return {"success": True, "test_files": ["tests/test_example.py"]}

    result = local_ai_repo("affected_tests")
    assert result["local_handoff"]["actions"] == ["delegate"]
