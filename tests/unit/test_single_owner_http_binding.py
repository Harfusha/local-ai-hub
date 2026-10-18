"""Repository, task and session boundaries after removing HTTP tenancy."""

from collections import deque
from email.message import Message
from types import SimpleNamespace
import threading

import pytest

from local_ai_hub import http_server


@pytest.fixture
def bound_handler(monkeypatch, tmp_path):
    from local_ai_hub.project_config import resolve_project_context

    coordination_id = resolve_project_context(tmp_path, tmp_path / "state").coordination_id
    task = SimpleNamespace(
        context=SimpleNamespace(repository_id=coordination_id, session_id="chat-one"),
        checkpoint=SimpleNamespace(state_data={"_agent_task_scope": {"version": 2, "repo_root": str(tmp_path)}}),
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {"api_token": "a" * 32, "allowed_roots": [str(tmp_path)]}},
        agent_state=SimpleNamespace(db_path=str(tmp_path / "state" / "agent_state.sqlite")),
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-one" else None),
    ))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.headers = Message()
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    return handler


def test_owner_global_memory_remains_global_with_api_token(bound_handler):
    payload = {"action": "find", "scope": "global"}
    assert bound_handler._bind_memory_payload(payload)
    assert payload == {"action": "find", "scope": "global"}
    assert "_authorization_tenant" not in bound_handler.__dict__


def test_owner_global_memory_query_is_not_rewritten_to_session(bound_handler):
    query = {"scope": ["global"]}
    assert bound_handler._bind_memory_query(query)
    assert query == {"scope": ["global"]}


def test_task_creation_preserves_actual_session(bound_handler, tmp_path):
    payload = {"root": str(tmp_path), "context": {"session_id": "chat-two"}}
    assert bound_handler._bind_task_payload(payload)
    assert payload["context"] == {
        "repository_id": bound_handler._request_task("task-one", str(tmp_path)).context.repository_id,
        "session_id": "chat-two",
    }
    assert payload["context"]["repository_id"] != str(tmp_path.resolve())
    assert payload["root"] == payload["repo_root"] == str(tmp_path.resolve())
    assert "tenant" not in payload


def test_task_binding_preserves_matching_logical_project_identity(bound_handler, tmp_path):
    expected = bound_handler._request_task("task-one", str(tmp_path)).context.repository_id
    payload = {
        "root": str(tmp_path),
        "context": {
            "repository_id": expected, "clone_id": "clone-a", "worktree_id": "worktree-a",
            "branch": "main", "task_id": "task-one", "session_id": "chat-one",
        },
    }

    assert bound_handler._bind_task_payload(payload)
    assert payload["context"] == {
        "repository_id": expected, "clone_id": "clone-a", "worktree_id": "worktree-a",
        "branch": "main", "task_id": "task-one", "session_id": "chat-one",
    }


def test_task_binding_rejects_mismatched_logical_project_identity(bound_handler, tmp_path):
    payload = {"root": str(tmp_path), "context": {"repository_id": "another-project-id"}}

    assert not bound_handler._bind_task_payload(payload)
    assert bound_handler.responses[-1][0] == 403
    assert bound_handler.responses[-1][1]["error_code"] == "repository_identity_mismatch"
    assert payload["context"]["repository_id"] == "another-project-id"


def test_task_binding_still_requires_repo_root_to_match_physical_root(bound_handler, tmp_path):
    other = tmp_path / "other-root"
    other.mkdir()
    payload = {"root": str(tmp_path), "repo_root": str(other), "context": {}}

    assert not bound_handler._bind_task_payload(payload)
    assert bound_handler.responses[-1][0] == 403
    assert bound_handler.responses[-1][1]["error_code"] == "root_not_allowed"


@pytest.mark.parametrize("value", [None, "", False])
def test_task_binding_rejects_retired_context_identity_by_presence(bound_handler, tmp_path, value):
    payload = {"root": str(tmp_path), "context": {"tenant": value}}

    assert not bound_handler._bind_task_payload(payload)
    assert bound_handler.responses[-1][0] == 400


def test_task_repository_ownership_does_not_depend_on_session(bound_handler, tmp_path):
    task = bound_handler._request_task("task-one", str(tmp_path))
    assert task.context.session_id == "chat-one"
    other = tmp_path / "other-repository"
    other.mkdir()
    assert bound_handler._request_task("task-one", str(other)) is None
    assert bound_handler.responses[-1][0] == 404


def test_session_memory_requires_explicit_session_id(bound_handler):
    assert not bound_handler._bind_memory_payload({"action": "find", "scope": "session"})
    assert bound_handler.responses[-1][0] == 400


def test_session_memory_preserves_explicit_session(bound_handler):
    payload = {"action": "find", "scope": "session", "session_id": "chat-two"}
    assert bound_handler._bind_memory_payload(payload)
    assert payload["scope_id"] == "chat-two"
    assert "tenant" not in payload


@pytest.mark.parametrize("scope", ["repository", "clone", "worktree", "branch", "task"])
def test_scoped_memory_without_root_rejects(bound_handler, scope):
    assert not bound_handler._bind_memory_payload({"action": "find", "scope": scope})
    assert bound_handler.responses[-1][1]["error_code"] == "root_required"


def test_task_memory_checks_repository_ownership(bound_handler, tmp_path):
    other = tmp_path / "other-repository"
    other.mkdir()
    assert not bound_handler._bind_memory_payload({
        "action": "find", "scope": "task", "root": str(other), "task_id": "task-one",
    })
    assert bound_handler.responses[-1][0] == 404


def test_memory_conflicting_provenance_root_rejects(bound_handler, tmp_path):
    other = tmp_path / "other-repository"
    other.mkdir()
    assert not bound_handler._bind_memory_payload({
        "action": "record", "root": str(tmp_path),
        "record": {"scope": "repository", "provenance": {"root": str(other)}},
    })
    assert bound_handler.responses[-1][1]["error_code"] == "root_not_allowed"


def test_cross_project_roots_remain_distinct_without_owner_partition(bound_handler, tmp_path):
    other = tmp_path / "other-repository"
    other.mkdir()
    payload = {"roots": [str(tmp_path), str(other)], "origin_root": str(other)}
    assert bound_handler._bind_multi_repository_payload(payload)
    assert payload["roots"] == [str(tmp_path.resolve()), str(other.resolve())]
    assert payload["origin_root"] == str(other.resolve())
    assert "tenant" not in payload


def test_rag_root_is_authorized_before_workspace_binding(bound_handler, tmp_path):
    class WorkspaceRag:
        def __init__(self):
            self.checked = []
            self.searches = []

        def require_workspace_root(self, *, workspace, root):
            self.checked.append((workspace, root))
            if workspace != f"workspace:{root}":
                raise ValueError("workspace is bound to another root")

        def search(self, query, *, workspace, **kwargs):
            self.searches.append((query, workspace))
            return {"success": True}

    rag = WorkspaceRag()
    # Match the HTTP dispatch order: allowed-root binding precedes RAG access.
    payload = {"root": str(tmp_path), "workspace": "workspace:wrong-root", "query": "needle"}
    assert bound_handler._bind_repository_root_payload(payload)
    with pytest.raises(ValueError, match="another root"):
        rag.require_workspace_root(workspace=payload["workspace"], root=payload["root"])
    assert rag.checked == [("workspace:wrong-root", str(tmp_path.resolve()))]
    assert rag.searches == []


def test_rag_request_from_unauthorized_root_stops_before_workspace_access(bound_handler, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    http_server.APP.config["security"]["allowed_roots"] = [str(allowed)]
    other = tmp_path / "outside"
    other.mkdir()
    calls = []
    payload = {"root": str(other), "workspace": "workspace:outside", "query": "needle"}

    assert not bound_handler._bind_repository_root_payload(payload)
    assert bound_handler.responses[-1][1]["error_code"] == "root_not_allowed"
    assert calls == []


def test_bind_root_reports_confinement_failure_as_response(bound_handler, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    http_server.APP.config["security"]["allowed_roots"] = [str(allowed)]
    other = tmp_path / "outside"
    other.mkdir()

    assert bound_handler._bind_root(str(other)) is None
    assert bound_handler.responses[-1][0] == 403
    assert bound_handler.responses[-1][1]["error_code"] == "root_not_allowed"


def test_context_keeps_real_session_and_rejects_mismatch(bound_handler, tmp_path):
    payload = {"root": str(tmp_path), "task_id": "task-one", "session_id": "chat-one"}
    assert bound_handler._bind_context_payload(payload)
    assert payload["session_id"] == "chat-one"
    assert not bound_handler._bind_context_payload({
        "root": str(tmp_path), "task_id": "task-one", "session_id": "chat-two",
    })
    assert bound_handler.responses[-1][0] == 403


def test_context_can_resolve_repository_from_stored_task(bound_handler, tmp_path):
    payload = {"task_id": "task-one"}
    assert bound_handler._bind_context_payload(payload)
    assert payload["root"] == str(tmp_path.resolve())
    assert "session_id" not in payload
    assert "tenant" not in payload


def test_task_blackboard_still_rejects_other_board(bound_handler, tmp_path):
    assert not bound_handler._bind_task_board_query({
        "root": [str(tmp_path)], "task_id": ["task-one"], "board_id": ["other-task"],
    })
    assert bound_handler.responses[-1][0] == 403


def test_json_retired_identity_rejects_even_null(bound_handler):
    bound_handler.headers["Content-Type"] = "application/json"
    bound_handler._read_body = lambda **_kwargs: b'{"tenant":null}'
    with pytest.raises(http_server.RequestBodyError, match="tenant"):
        bound_handler._read_json()


def test_post_query_retired_identity_rejects_before_authorization(bound_handler):
    bound_handler.path = "/api/search?tenant="
    bound_handler.command = "POST"
    bound_handler._validate_host_and_origin = lambda: True
    assert not bound_handler._require_authorized()
    assert bound_handler.responses[-1][0] == 400


def test_rate_limit_is_one_bounded_installation_window(monkeypatch):
    server = http_server.LocalAIHTTPServer.__new__(http_server.LocalAIHTTPServer)
    server._rate_lock = threading.Lock()
    server._rate_window = deque()
    server.configure_rate_limit(2, 10)
    now = [10.0]
    monkeypatch.setattr(http_server.time, "monotonic", lambda: now[0])
    assert server.check_rate_limit()
    assert server.check_rate_limit()
    assert not server.check_rate_limit()
    now[0] = 21.0
    assert server.check_rate_limit()
    assert len(server._rate_window) == 1
    with pytest.raises(TypeError):
        server.check_rate_limit(tenant=None)
