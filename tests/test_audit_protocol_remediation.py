from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub.rag import RAGStore
from local_ai_hub.task_context import build_context_request


@pytest.mark.parametrize("detail", ["brief"])
def test_status_reports_explain_dependency_degradation(monkeypatch, detail):
    from local_ai_hub import mcp_server as module
    failed = {"degraded": True, "deadline_ms": 250, "status": "timeout"}
    raw = {"success": False, "hub_online": True, "degraded": True,
           "dependency_status": {"accelerators": failed,
                                 "healthy": {"degraded": False},
                                 "invalid": None, "coerced": {"degraded": "true"}}}
    monkeypatch.setattr(module.CLIENT, "get", lambda *args, **kwargs: raw)
    result = module.local_ai_status(detail=detail, max_response_tokens=1200)
    assert result["success"] is False
    assert result["hub_online"] is True
    assert result["degraded"] is True
    assert result["dependency_status"] == {"accelerators": failed}


@pytest.mark.parametrize("field", ["task_id", "session_id", "repository_id", "clone_id", "worktree_id", "branch"])
@pytest.mark.parametrize("value", [123, " invalid", "invalid\0id", "x" * 201])
def test_context_identity_is_rejected_without_coercion(field, value):
    with pytest.raises(ValueError):
        build_context_request({field: value})


@pytest.mark.parametrize("field", ["include_diagnostics", "_scoped_task_only"])
@pytest.mark.parametrize("value", ["false", 0, [], None])
def test_context_flags_are_exact_booleans(field, value):
    with pytest.raises(ValueError):
        build_context_request({field: value})


@pytest.mark.parametrize("value", [False, 0, "100", float("nan"), 1.5])
def test_context_budget_does_not_default_malformed_falsey_values(value):
    with pytest.raises(ValueError):
        build_context_request({"token_budget": value})


def test_parallel_commands_forward_explicit_execution_context(tmp_path):
    calls = []
    broker = object.__new__(CommandBroker)
    broker.run = lambda command, **kwargs: calls.append((command, kwargs)) or {"success": True}
    fence, project = object(), object()
    result = broker.run_parallel([{
        "id": "first", "command": "python -m pytest", "task_id": "explicit-task",
        "criterion": "tests pass", "record_verification": False,
        "_work_attempt_fence": fence, "project_context": project,
        "env": {"MODE": "test"},
    }], cwd=str(tmp_path))
    assert result["success"] is True
    assert len(calls) == 1
    options = calls[0][1]
    assert options["task_id"] == "explicit-task"
    assert options["criterion"] == "tests pass"
    assert options["record_verification"] is False
    assert options["_work_attempt_fence"] is fence
    assert options["project_context"] is project
    assert options["env"] == {"MODE": "test"}


@pytest.mark.parametrize("items", [
    [{"id": "same", "cmd": "first"}, {"id": "same", "cmd": "second"}],
    [{"cmd": "first"}, {"cmd": "second", "unknown_option": True}],
    [{"id": 5, "cmd": "first"}],
])
def test_invalid_parallel_batch_is_rejected_before_any_execution(items, tmp_path):
    calls = []
    broker = object.__new__(CommandBroker)
    broker.run = lambda *args, **kwargs: calls.append(args) or {"success": True}
    result = broker.run_parallel(items, cwd=str(tmp_path))
    assert result["success"] is False
    assert calls == []


def test_diagram_user_metadata_cannot_replace_source_provenance(tmp_path, monkeypatch):
    image = tmp_path / "real.png"
    image.write_bytes(b"fixture")
    store = object.__new__(RAGStore)
    store.config = {}
    store._prepare_ingest_workspace = lambda **kwargs: (tmp_path, "workspace")
    store._confined_diagram_path = lambda *args: image
    captured = []
    store.ingest_document = lambda **kwargs: captured.append(kwargs) or {"success": True}
    result = store.ingest_diagram(root=str(tmp_path), workspace="workspace", image_path=str(image),
                                  metadata={"image_path": "fake.png", "type": "forged"})
    assert result.get("success") is False
    assert captured == []


def test_code_index_projection_keeps_the_actual_query_term_denominator():
    from local_ai_hub.mcp_server import _code_index_page_with_prefix
    symbols = [{"name": "target", "path": "app.py", "matched_terms": ["target", "symbol", "lookup"]}]
    raw = {"success": True, "symbols": symbols, "has_more": True, "total_matches": 2,
           "coverage": {"query_term_count": 3, "matched_term_count": 3, "query_term_coverage": 1.0}}
    result = _code_index_page_with_prefix(raw, raw, symbols, 1)
    assert result["coverage"]["query_term_count"] == 3
    assert result["coverage"]["query_term_coverage"] == 1.0
