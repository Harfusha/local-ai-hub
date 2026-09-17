from __future__ import annotations

import inspect
import importlib
import sys
from pathlib import Path
from typing import Literal, get_args, get_origin, get_type_hints
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from local_ai_hub import mcp_server as local_ai_mcp  # noqa: E402
from local_ai_hub.features import FeatureSet  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_profile_catalog(monkeypatch):
    # Routing tests must not inherit a developer's disabled installed profiles.
    monkeypatch.setattr(local_ai_mcp, 'PROFILE_CATALOG', local_ai_mcp.OllamaSubagentCatalog({}))


def test_public_action_parameters_are_explicit_literals() -> None:
    expected = {
        "local_ai_task": {"delegate", "reason", "continue", "review", "second_opinion", "compress", "route", "batch", "benchmark", "hardware_benchmark", "evaluation_record", "evaluation_report", "submit", "status", "wait", "result", "cancel", "candidate_create", "candidate_promote", "speculative_draft", "vision", "transcribe", "eval_suite", "prompt_eval", "eval_drift", "complete_code", "scaffold"},
        "local_ai_rag": {"index", "search", "list", "docset_index", "docset_search", "ingest_document", "ingest_diagram"},
        "local_ai_coord": {"claim", "renew", "release", "leases", "memo_put", "memo_get", "memo_search", "memo_delete", "task_create", "task_get", "task_checkpoint", "task_rollback", "task_transition", "task_resume", "task_list", "task_complete", "task_fail", "task_heartbeat", "memory_record", "memory_get", "memory_find", "memory_promote", "memory_reap", "context_compile", "verify_receipt", "verify_completion", "negative_knowledge_record", "negative_knowledge_find", "incident_decision", "blackboard_update", "blackboard_get", "blackboard_list", "blackboard_delete", "blackboard_merge", "swarm_dispatch", "swarm_step", "swarm_status", "swarm_list", "swarm_cancel", "worktree_lease", "worktree_release", "pubsub_publish", "pubsub_poll", "simulate_merge", "relation_record", "relation_find", "relation_traverse", "curate_dataset", "task_sync", "task_zombie_reap", "task_cleanup_worktree"},
        "local_ai_command": {"run", "cancel", "classify", "discover", "stats", "repair_loop", "auto_fix", "run_affected", "format", "lint_fix", "spawn_daemon", "daemon_status", "stop_daemon", "http_probe", "stash_save", "stash_restore", "record_mock", "replay_mock", "diff_hunk_stage", "flaky_detect", "webhook_replay", "mock_server", "mock_server_start", "mock_server_stop", "mock_server_status", "patch_and_verify", "preflight"},
    }
    for name, values in expected.items():
        annotation = get_type_hints(getattr(local_ai_mcp, name))["action"]
        assert get_origin(annotation) is Literal, name
        assert set(get_args(annotation)) == values, name
    repo_action = get_type_hints(local_ai_mcp.local_ai_repo)["action"]
    assert get_origin(repo_action) is Literal
    assert "batch_replace" not in get_args(repo_action)


def test_live_mcp_catalog_uses_feature_specific_batch_schema(tmp_path: Path, monkeypatch) -> None:
    disabled_config = tmp_path / "disabled.toml"
    disabled_config.write_text("[features]\nbatch_replacement = false\n", encoding="utf-8")
    enabled_config = tmp_path / "enabled.toml"
    enabled_config.write_text("[features]\nbatch_replacement = true\n", encoding="utf-8")
    try:
        monkeypatch.setenv("LOCAL_AI_CONFIG", str(disabled_config))
        importlib.reload(local_ai_mcp)
        disabled_schema = local_ai_mcp.mcp._tool_manager._tools["local_ai_repo"].parameters["properties"]
        assert "batch_replace" not in disabled_schema["action"].get("enum", [])
        assert "edits" not in disabled_schema
        assert "dry_run" not in disabled_schema
        assert "edits" not in inspect.signature(local_ai_mcp.local_ai_repo).parameters
        assert "dry_run" not in inspect.signature(local_ai_mcp.local_ai_repo).parameters
        disabled_action = get_type_hints(local_ai_mcp.local_ai_repo)["action"]
        assert get_origin(disabled_action) is Literal
        assert "batch_replace" not in get_args(disabled_action)

        monkeypatch.setenv("LOCAL_AI_CONFIG", str(enabled_config))
        importlib.reload(local_ai_mcp)
        enabled_schema = local_ai_mcp.mcp._tool_manager._tools["local_ai_repo"].parameters["properties"]
        assert "batch_replace" in enabled_schema["action"]["enum"]
        assert "edits" in enabled_schema
        assert "dry_run" in enabled_schema
        assert "edits" in inspect.signature(local_ai_mcp.local_ai_repo).parameters
        assert "dry_run" in inspect.signature(local_ai_mcp.local_ai_repo).parameters
        enabled_action = get_type_hints(local_ai_mcp.local_ai_repo)["action"]
        assert get_origin(enabled_action) is Literal
        assert "batch_replace" in get_args(enabled_action)
    finally:
        monkeypatch.delenv("LOCAL_AI_CONFIG", raising=False)
        importlib.reload(local_ai_mcp)


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


def test_dynamic_descriptions_make_first_choice_routing_explicit() -> None:
    descriptions = {
        "task": local_ai_mcp._desc_task(),
        "repo": local_ai_mcp._desc_repo(),
        "command": local_ai_mcp._desc_command(),
        "coord": local_ai_mcp._desc_coord(),
        "work": local_ai_mcp._desc_work(),
        "artifact": local_ai_mcp._desc_artifact(),
    }

    assert "repository navigation, symbols, and impact" in descriptions["repo"]
    assert "exact source or log slice" in descriptions["artifact"]
    assert "test, lint, typecheck, or build" in descriptions["command"]
    assert "ownership, checkpoints, and verification receipts" in descriptions["coord"]
    assert "local diagnosis, boilerplate, or second opinion" in descriptions["task"]
    assert "closed, low-risk work" in descriptions["work"]
    assert "terminal=true and retryable=false" in descriptions["repo"]
    assert "terminal=true and retryable=false" in descriptions["command"]
    assert "Mutations never cache or single-flight" in descriptions["command"]


def test_durable_routing_requires_checkpointed_contracts_and_closed_handoffs() -> None:
    descriptions = {
        "task": local_ai_mcp._desc_task(),
        "coord": local_ai_mcp._desc_coord(),
        "work": local_ai_mcp._desc_work(),
    }

    assert "deterministic command parsing" in descriptions["task"]
    assert "task contracts" in descriptions["coord"]
    assert "checkpoints" in descriptions["coord"]
    assert "verified handoff" in descriptions["work"]
    assert "micro-edits" in descriptions["work"]
    assert "live discussion" in descriptions["work"]


def test_invalid_repo_action_lists_next_bounded_actions() -> None:
    result = local_ai_mcp.local_ai_repo(action="not_a_real_action")
    assert result["success"] is False
    assert "Valid actions:" in result["error"]
    assert "review_diff" in result["error"]
    assert "security_audit" in result["error"]


def test_local_ai_repo_forwards_explicit_batch_replace_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "FEATURES", FeatureSet({"features": {"repo": True, "batch_replacement": True}}))
    captured = {}
    edits = [{"path": "example.py", "old": "before", "new": "after"}]

    def fake_post(path, payload, **kwargs):
        captured.update({"path": path, **payload})
        return {"success": True, "applied": False, "dry_run": True}

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", fake_post)
    result = local_ai_mcp.local_ai_repo(
        action="batch_replace",
        root=str(ROOT),
        edits=edits,
        dry_run=True,
    )

    assert result["success"] is True
    assert captured["path"] == "/api/code/batch_replace"
    assert captured["edits"] == edits
    assert captured["dry_run"] is True
    assert "staged" not in captured


def test_local_ai_repo_batch_replace_does_not_use_staged_as_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "FEATURES", FeatureSet({"features": {"repo": True, "batch_replacement": True}}))
    captured = {}
    edits = [{"path": "example.py", "old": "before", "new": "after"}]

    def fake_post(path, payload, **kwargs):
        captured.update({"path": path, **payload})
        return {"success": True, "applied": True, "dry_run": False}

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", fake_post)
    result = local_ai_mcp.local_ai_repo(
        action="batch_replace",
        root=str(ROOT),
        edits=edits,
        staged=True,
    )

    assert result["success"] is True
    assert captured["dry_run"] is False
    assert "staged" not in captured


def test_local_ai_repo_batch_replacements_require_explicit_edits(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "FEATURES", FeatureSet({"features": {"repo": True, "batch_replacement": True}}))
    def unexpected_post(*_args, **_kwargs):
        pytest.fail("batch replacement must not reuse generic evidence payloads")

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", unexpected_post)
    result = local_ai_mcp.local_ai_repo(
        action="batch_replace",
        root=str(ROOT),
        evidence=[{"path": "example.py", "old": "before", "new": "after"}],
    )

    assert result["success"] is False
    assert "edits" in result["error"]


def test_local_ai_repo_enriches_search_when_source_requested(monkeypatch) -> None:
    monkeypatch.setattr(local_ai_mcp, "FEATURES", FeatureSet({"features": {"repo": True, "enriched_search": True}}))
    captured = {}

    def fake_post(path, payload, **kwargs):
        captured.update({"path": path, **payload})
        return {"success": True, "results": []}

    monkeypatch.setattr(local_ai_mcp.CLIENT, "post", fake_post)
    result = local_ai_mcp.local_ai_repo(
        action="search",
        root=str(ROOT),
        query="target symbol",
        include_code=True,
    )

    assert result["success"] is True
    assert captured["path"] == "/api/search"
    assert captured["query"] == "target symbol"
    assert captured["enrich"] is True


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
