"""Deferred boundary coverage for canonical local_ai_repo file and ID inputs."""
from __future__ import annotations

import asyncio

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import (
    operation_input_schema,
    operation_tool_input_schema,
    validate_operation_arguments,
)


_ALIASES = [
    ("ast_outline", {"path": "src/a.py", "query": "src/old.py"}),
    ("affected_tests", {"path": "src/a.py", "query": "src/old.py"}),
    ("code_invariants", {"path": "src/a.py", "task": "src/old.py"}),
    ("profile_digest", {"path": "profile.prof", "query": "old.prof"}),
    ("schema_inspect", {"path": "db.sqlite", "task": "old.sqlite"}),
    ("generate_types", {"path": "src/a.py", "diff": ""}),
    ("complexity", {"path": "src/a.py", "query": "src/old.py"}),
    ("declaration", {"query": "Widget", "task": "OldWidget"}),
    ("ast_refactor", {"path": "src/a.py", "old_symbol": "Old", "new_symbol": "New", "diff": "New"}),
    ("context_compile", {"task_id": "task-1", "query": "task-2"}),
    ("verify_completion", {"task_id": "task-1", "task": "task-2"}),
]


def _make_repo_active(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)


@pytest.mark.parametrize(("action", "arguments"), _ALIASES)
def test_registered_repo_dispatch_rejects_retired_aliases_before_client(
    action, arguments, monkeypatch, tmp_path,
):
    _make_repo_active(monkeypatch)
    calls = []

    class DummyClient:
        def post(self, url, payload, **kwargs):
            calls.append((url, payload))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": action, "root": str(tmp_path), **arguments,
    }))

    assert calls == []
    assert "400" in str(result)


@pytest.mark.parametrize(("action", "canonical", "required", "forbidden"), [
    ("ast_outline", {"root": ".", "path": "src/a.py"}, ["path"], ["query", "task"]),
    ("affected_tests", {"root": "."}, [], ["query", "task"]),
    ("code_invariants", {"root": "."}, [], ["query", "task"]),
    ("profile_digest", {"root": ".", "path": "profile.prof"}, ["path"], ["query", "task"]),
    ("schema_inspect", {"root": "."}, [], ["query", "task"]),
    ("generate_types", {"root": ".", "path": "src/a.py"}, ["path"], ["query", "task", "diff"]),
    ("complexity", {"root": "."}, [], ["query", "task"]),
    ("declaration", {"root": ".", "query": "Widget"}, ["query"], ["task"]),
    ("ast_refactor", {"root": ".", "old_symbol": "Old", "new_symbol": "New"}, ["old_symbol", "new_symbol"], ["query", "task", "diff"]),
])
def test_repo_operation_schemas_match_canonical_inputs(action, canonical, required, forbidden):
    schema = operation_input_schema("local_ai_repo", action)
    assert set(required) <= set(schema.get("required", []))
    assert not set(forbidden) & set(schema.get("properties", {}))
    assert validate_operation_arguments("local_ai_repo", action, canonical) is None
    for field in required:
        missing = dict(canonical)
        missing.pop(field, None)
        assert validate_operation_arguments("local_ai_repo", action, missing) is not None

    public_schema = operation_tool_input_schema("local_ai_repo")
    assert public_schema["additionalProperties"] is False


@pytest.mark.parametrize(("action", "arguments", "url", "payload_key", "expected"), [
    ("ast_outline", {"path": "src/a.py"}, "/api/code/ast_outline", "path", "src/a.py"),
    ("affected_tests", {}, "/api/repo/affected_tests", "paths", None),
    ("code_invariants", {"path": "src/a.py"}, "/api/repo/code_invariants", "path", "src/a.py"),
    ("profile_digest", {"path": "profile.prof"}, "/api/repo/profile_digest", "profile_path", None),
    ("schema_inspect", {"path": "db.sqlite"}, "/api/repo/schema_inspect", "db_path", "db.sqlite"),
    ("generate_types", {"path": "src/a.py"}, "/api/repo/generate_types", "path", "src/a.py"),
    ("complexity", {"path": "src/a.py"}, "/api/repo/complexity", "path", "src/a.py"),
    ("declaration", {"query": "Widget", "path": "src/a.py"}, "/api/code/declaration", "symbol", "Widget"),
    ("ast_refactor", {"path": "src/a.py", "old_symbol": "Old", "new_symbol": "New"}, "/api/code/ast_rename", "old_symbol", "Old"),
])
def test_repo_canonical_operation_dispatch_payloads(
    action, arguments, url, payload_key, expected, monkeypatch, tmp_path,
):
    _make_repo_active(monkeypatch)
    calls = []

    class DummyClient:
        def post(self, path, payload, **kwargs):
            calls.append((path, payload))
            return {"success": True}

    monkeypatch.setattr(mcp_server, "CLIENT", DummyClient())
    result = mcp_server._local_ai_repo_impl(action, root=str(tmp_path), **arguments)

    assert result["success"] is True
    assert len(calls) == 1
    assert calls[0][0] == url
    if expected is not None:
        assert calls[0][1][payload_key] == expected
    elif action == "affected_tests":
        assert calls[0][1][payload_key] is None
    elif action == "profile_digest":
        assert calls[0][1][payload_key].endswith("profile.prof")

