"""Deferred regression coverage for canonical repo operation input fields."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import (
    operation_input_schema,
    validate_operation_arguments,
)


_RETIRED_INPUTS = [
    ("context", {"query": "current", "task": "retired"}),
    ("solve", {"task": "current", "query": "retired"}),
    ("delegate", {"task": "current", "query": "retired"}),
    ("investigate", {"query": "current", "task": "retired"}),
    ("diagnose", {"query": "current", "diff": "retired"}),
    ("search", {"query": "current", "task": "retired"}),
    ("code_index", {"query": "current", "task": "retired"}),
    ("semantic", {"query": "current", "task": "retired"}),
    ("deterministic", {"query": "current", "task": "retired"}),
    ("route", {"query": "current", "path": "src/a.py", "task": "retired"}),
    ("refactor_impact", {"query": "Widget", "task": "retired"}),
    ("resolve_imports", {"query": "Widget", "task": "retired"}),
    ("generate_tests", {"query": "Widget", "task": "retired"}),
    ("validate_patch", {"query": "patch text", "task": "retired"}),
    ("generate_mocks", {"query": "Widget", "task": "retired"}),
    ("synthesize_commit", {"query": "hint", "task": "task-legacy"}),
    ("cross_project_symbols", {"query": "Widget", "task": "retired"}),
    ("cross_project_impact", {"query": "Widget", "task": "retired"}),
    ("generate_dataset", {"query": "Widget", "path": "retired.py"}),
    ("explain_query", {"query": "SELECT 1", "task": "retired"}),
    ("api_spec", {"task": "retired"}),
    ("dependency_slice", {"query": "Widget", "relation": "retired"}),
    ("structural_search", {"query": "pattern", "task": "retired"}),
    ("git_history_search", {"query": "change", "task": "retired"}),
    ("generate_tests_for_diff", {"diff": "patch", "query": "retired"}),
    ("cross_repo_contract", {"path": "C:/frontend", "workspace": "retired"}),
    ("circular_dependencies", {"language": "python", "query": "retired"}),
    ("migration_drift", {"path": "db.sqlite", "query": "retired"}),
    ("package_audit", {"path": "lockfile", "task": "retired"}),
    ("git_diff", {"path": "src/a.py", "query": "retired"}),
    ("mutation_test", {"path": "src/a.py", "query": "retired"}),
    ("type_stubs", {"path": "src/a.py", "query": "retired"}),
    ("split_changes", {"path": "src/a.py", "query": "retired"}),
    ("skeletonize", {"query": "source", "task": "retired"}),
]


def _make_active(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    monkeypatch.setattr(mcp_server.FEATURES, "serena", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_semantic", lambda: True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)


@pytest.mark.parametrize(("action", "fields"), _RETIRED_INPUTS)
def test_registered_repo_handler_rejects_retired_fields_before_dispatch(
    action, fields, monkeypatch, tmp_path,
):
    _make_active(monkeypatch)
    calls = []

    class DummyClient:
        def post(self, url, payload, **kwargs):
            calls.append((url, payload))
            return {"success": True}

        def get(self, url, **kwargs):
            calls.append((url, None))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": action, "root": str(tmp_path), **fields,
    }))

    assert calls == []
    assert "400" in str(result)


@pytest.mark.parametrize(("action", "canonical", "forbidden"), [
    ("context", {"root": ".", "query": "context"}, ["task"]),
    ("solve", {"root": ".", "task": "implement"}, ["query", "diff"]),
    ("delegate", {"root": ".", "task": "implement"}, ["query", "diff"]),
    ("investigate", {"root": ".", "query": "find"}, ["task", "diff"]),
    ("api_spec", {"root": "."}, ["task"]),
    ("generate_tests_for_diff", {"root": ".", "diff": "patch"}, ["query", "task", "path"]),
    ("cross_repo_contract", {"root": ".", "path": "C:/frontend"}, ["query", "workspace", "task"]),
    ("circular_dependencies", {"root": ".", "language": "python"}, ["query", "task"]),
    ("skeletonize", {"root": ".", "path": "src/a.py"}, ["task", "diff"]),
])
def test_repo_action_schema_accepts_only_canonical_fields(action, canonical, forbidden):
    schema = operation_input_schema("local_ai_repo", action)
    assert validate_operation_arguments("local_ai_repo", action, canonical) is None
    for field in forbidden:
        assert field not in schema.get("properties", {}) or validate_operation_arguments(
            "local_ai_repo", action, {**canonical, field: "retired"},
        ) is not None


@pytest.mark.parametrize(("action", "canonical", "alias"), [
    ("investigate", {"query": "find"}, {"task": "find"}),
    ("context", {"query": "find"}, {"task": "find"}),
    ("solve", {"task": "implement"}, {"query": "implement"}),
    ("generate_tests_for_diff", {"diff": "patch"}, {"query": "patch"}),
    ("migration_drift", {"path": "db.sqlite"}, {"query": "db.sqlite"}),
    ("circular_dependencies", {"language": "python"}, {"query": "python"}),
])
def test_direct_repo_impl_rejects_alias_even_with_canonical_value(
    action, canonical, alias, monkeypatch, tmp_path,
):
    _make_active(monkeypatch)
    calls = []
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(
        post=lambda *args, **kwargs: calls.append(args),
        get=lambda *args, **kwargs: calls.append(args),
    ))
    result = mcp_server._local_ai_repo_impl(
        action, root=str(tmp_path), **canonical, **alias,
    )
    assert result["success"] is False
    assert calls == []


@pytest.mark.parametrize(("action", "fields", "url", "payload_key", "expected"), [
    ("investigate", {"query": "find call"}, "/api/repo/investigate", "query", "find call"),
    ("diagnose", {"query": "traceback"}, "/api/repo/diagnose", "text", "traceback"),
    ("solve", {"task": "implement fix"}, "/api/solve/repo", "task", "implement fix"),
    ("generate_tests_for_diff", {"diff": "diff body"}, "/api/repo/generate_tests_for_diff", "diff", "diff body"),
    ("migration_drift", {"path": "db.sqlite"}, "/api/repo/migration_drift", "db_path", "db.sqlite"),
    ("circular_dependencies", {"language": "python"}, "/api/repo/circular_dependencies", "language", "python"),
    ("cross_repo_contract", {"path": "C:/frontend"}, "/api/repo/cross_repo_contract", "frontend_root", "C:/frontend"),
    ("skeletonize", {"query": "def f(): pass"}, "/api/repo/skeletonize", "code", "def f(): pass"),
])
def test_direct_repo_impl_dispatches_canonical_value(
    action, fields, url, payload_key, expected, monkeypatch, tmp_path,
):
    _make_active(monkeypatch)
    calls = []

    class DummyClient:
        def post(self, path, payload, **kwargs):
            calls.append((path, payload))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    result = mcp_server._local_ai_repo_impl(action, root=str(tmp_path), **fields)

    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0][0] == url
    assert calls[0][1][payload_key] == expected
