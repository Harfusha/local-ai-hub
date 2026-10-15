"""Deferred coverage for full repo-action validation in wrapper scopes."""
from __future__ import annotations

import pytest

from local_ai_hub import mcp_server


def _activate_repo(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        return {"success": True}


@pytest.mark.parametrize(
    ("action", "input_field", "input_value", "endpoint", "payload_field"),
    [
        ("diagnose", "query", "missing bounds check", "/api/repo/diagnose", "text"),
        ("type_stubs", "path", "src/module.py", "/api/repo/type_stubs", "file"),
        ("solve", "task", "explain dispatch", "/api/solve/repo", "task"),
    ],
)
@pytest.mark.parametrize("public_wrapper", [False, True])
def test_required_repo_inputs_survive_scoped_validation(
    monkeypatch, tmp_path, action, input_field, input_value, endpoint,
    payload_field, public_wrapper,
):
    _activate_repo(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    call = mcp_server.local_ai_repo if public_wrapper else mcp_server._local_ai_repo_impl

    result = call(action=action, root=str(tmp_path.resolve()), **{input_field: input_value})

    assert result["success"] is True
    assert len(client.calls) == 1
    assert client.calls[0][0] == endpoint
    assert client.calls[0][1][payload_field] == input_value


@pytest.mark.parametrize("public_wrapper", [False, True])
def test_repo_scoped_filter_rejection_keeps_required_query_in_validation(
    monkeypatch, tmp_path, public_wrapper,
):
    _activate_repo(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    call = mcp_server.local_ai_repo if public_wrapper else mcp_server._local_ai_repo_impl

    result = call(
        action="diagnose", root=str(tmp_path.resolve()),
        query="bounded query", max_commits=12,
    )

    assert result["success"] is False
    assert result["status_code"] == 400
    assert client.calls == []


@pytest.mark.parametrize("public_wrapper", [False, True])
def test_missing_required_repo_query_still_fails_closed(monkeypatch, tmp_path, public_wrapper):
    _activate_repo(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    call = mcp_server.local_ai_repo if public_wrapper else mcp_server._local_ai_repo_impl

    result = call(action="diagnose", root=str(tmp_path.resolve()))

    assert result["success"] is False
    assert client.calls == []


@pytest.mark.parametrize("public_wrapper", [False, True])
def test_ast_refactor_rejects_supplied_diff_through_both_wrappers(
    monkeypatch, tmp_path, public_wrapper,
):
    _activate_repo(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    call = mcp_server.local_ai_repo if public_wrapper else mcp_server._local_ai_repo_impl

    result = call(
        action="ast_refactor", root=str(tmp_path.resolve()), path="src/a.py",
        old_symbol="OldName", new_symbol="NewName", diff="renamed source",
    )

    assert result["success"] is False
    assert client.calls == []


@pytest.mark.parametrize(("retired_name", "retired_value"), [
    ("query", "old selector"), ("task", "old selector"),
])
@pytest.mark.parametrize("public_wrapper", [False, True])
def test_ast_outline_rejects_supplied_query_or_task_through_both_wrappers(
    monkeypatch, tmp_path, retired_name, retired_value, public_wrapper,
):
    _activate_repo(monkeypatch)
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    call = mcp_server.local_ai_repo if public_wrapper else mcp_server._local_ai_repo_impl

    result = call(
        action="ast_outline", root=str(tmp_path.resolve()), path="src/a.py",
        **{retired_name: retired_value},
    )

    assert result["success"] is False
    assert client.calls == []
