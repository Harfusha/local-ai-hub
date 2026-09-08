from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Literal, get_args, get_origin, get_type_hints

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from local_ai_hub import mcp_server as local_ai_mcp  # noqa: E402


def test_public_action_parameters_are_explicit_literals() -> None:
    expected = {
        "local_ai_task": {"delegate", "reason", "continue", "review", "second_opinion", "compress", "route", "batch", "benchmark", "hardware_benchmark", "evaluation_record", "evaluation_report", "submit", "status", "wait", "result", "cancel", "candidate_create", "candidate_promote"},
        "local_ai_repo": {"profile", "deterministic", "search", "map", "code_index", "semantic", "graph", "intelligence", "context", "route", "delegate", "solve", "review_diff", "impact", "refactor_impact", "resolve_imports", "generate_tests", "validate_patch", "audit_dependencies", "ast_outline", "test_matrix", "security_audit", "git_status", "synthesize_commit", "verify", "preprocess", "preprocess_status", "preprocess_refresh", "preprocess_pause", "preprocess_resume", "preprocess_cancel", "preprocess_unregister", "context_compile", "verify_receipt", "verify_completion", "cross_project_graph", "cross_project_symbols", "cross_project_impact", "cross_repo_graph", "cross_repo_symbols", "cross_repo_impact", "call_graph_diff", "semantic_diff"},
        "local_ai_rag": {"index", "search", "list"},
        "local_ai_coord": {"claim", "renew", "release", "leases", "memo_put", "memo_get", "memo_search", "memo_delete", "task_create", "task_get", "task_checkpoint", "task_transition", "task_resume", "task_list", "task_complete", "task_fail", "task_heartbeat", "memory_record", "memory_get", "memory_find", "memory_promote", "memory_reap", "context_compile", "verify_receipt", "verify_completion", "negative_knowledge_record", "negative_knowledge_find", "incident_decision", "blackboard_update", "blackboard_get", "blackboard_list", "blackboard_delete", "blackboard_merge", "swarm_dispatch", "swarm_step", "swarm_status"},
        "local_ai_command": {"run", "cancel", "classify", "discover", "stats", "repair_loop", "auto_fix"},
    }
    for name, values in expected.items():
        annotation = get_type_hints(getattr(local_ai_mcp, name))["action"]
        assert get_origin(annotation) is Literal, name
        assert set(get_args(annotation)) == values, name


def test_mcp_descriptions_explain_agent_tier_boundaries() -> None:
    descriptions = "\n".join(
        inspect.getdoc(getattr(local_ai_mcp, name)) or ""
        for name in ["local_ai_task", "local_ai_repo", "local_ai_rag", "local_ai_command", "local_ai_coord", "local_ai_artifact"]
    )
    assert "main agent" in descriptions
    assert "AGY" not in descriptions
    assert "bounded" in descriptions
    assert "Codex" in descriptions
    assert "does not route or manage" in descriptions
    assert "review_diff" in descriptions
    assert "security_audit" in descriptions


def test_invalid_repo_action_lists_next_bounded_actions() -> None:
    result = local_ai_mcp.local_ai_repo(action="not_a_real_action")
    assert result["success"] is False
    assert "Valid actions:" in result["error"]
    assert "review_diff" in result["error"]
    assert "security_audit" in result["error"]


def test_invalid_task_action_excludes_orchestration() -> None:
    result = local_ai_mcp.local_ai_task(action="not_a_real_action")
    assert result["success"] is False
    assert "bounded local-model" in result["error"]
    assert "peer subagents" in result["error"]


def test_local_ai_task_exposes_named_profile_fields() -> None:
    parameters = inspect.signature(local_ai_mcp.local_ai_task).parameters

    assert "profile" in parameters
    assert "root" in parameters
    assert "workspace" in parameters


def test_local_ai_task_forwards_continue_with_opaque_conversation_id(monkeypatch) -> None:
    captured = {}

    def fake_post(path, payload, **kwargs):
        captured.update({"path": path, **payload})
        return {"success": True, "conversation_id": payload["conversation_id"], "text": "doplnění"}

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", fake_post)
    result = local_ai_mcp.local_ai_task(
        action="continue",
        conversation_id="opaque-id",
        task="Doplň detaily.",
    )

    assert result["success"] is True
    assert captured == {
        "path": "/api/conversations/continue",
        "conversation_id": "opaque-id",
        "task": "Doplň detaily.",
        "context": "",
    }


def test_invalid_ollama_profile_returns_structured_error() -> None:
    result = local_ai_mcp.local_ai_task(action="delegate", profile="writer", task="x")

    assert result["success"] is False
    assert result["unsupported"] is True
    assert "qwen-explorer" in result["error"]


def test_named_profile_forwards_repo_root_to_existing_delegate_endpoint(monkeypatch) -> None:
    captured = {}

    def fake_post(path, payload, **kwargs):
        captured.update({"path": path, **payload})
        return {"success": True, "text": "návrh", "profile": payload.get("profile")}

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", fake_post)
    result = local_ai_mcp.local_ai_task(
        action="delegate",
        profile="qwen-explorer",
        root="C:\\repo",
        task="Najdi vstupní body",
    )

    assert result["success"] is True
    assert captured["path"] == "/api/delegate/repo"
    assert captured["profile"] == "qwen-explorer"
    assert captured["root"] == "C:\\repo"


def test_named_profile_requires_absolute_repository_root() -> None:
    result = local_ai_mcp.local_ai_task(
        action="delegate",
        profile="qwen-explorer",
        task="Najdi vstupní body",
    )

    assert result["success"] is False
    assert result["unsupported"] is True
    assert "absolute" in result["error"]


def test_named_profile_rejects_relative_repository_root() -> None:
    result = local_ai_mcp.local_ai_task(
        action="delegate",
        profile="qwen-explorer",
        root="repo",
        task="Najdi vstupní body",
    )

    assert result["success"] is False
    assert result["unsupported"] is True
    assert "absolute" in result["error"]
