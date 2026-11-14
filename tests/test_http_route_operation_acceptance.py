"""Operation-level HTTP acceptance for selected unlinked route families."""

from __future__ import annotations

import json
import subprocess
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import quote
from urllib import request as urllib_request

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract


def _urlopen_with_error_body(request):
    try:
        return urllib_request.urlopen(request)
    except HTTPError as exc:
        pytest.fail(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")


@pytest.fixture
def running_http_hub(tmp_path):
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    config_path.write_text(
        "\n".join(
            [
                "[server]",
                'bind = "127.0.0.1"',
                "port = 11435",
                f'state_dir = "{state_dir.as_posix()}"',
                "[security]",
                f'allowed_roots = ["{tmp_path.as_posix()}"]',
                "[agent_state]",
                "enabled = true",
            ]
        ),
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    app.agent_tasks.create(
        GoalContract(goal="HTTP route acceptance"),
        ScopeContext(
            repository_id=str(tmp_path),
            task_id="task-31",
            session_id="session:http-route-acceptance",
        ),
        task_id="task-31",
        repo_root=str(tmp_path),
    )
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", app
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        http_server.APP = previous_app
        app.close()


def test_http_get_agent_state_blackboard_forwards_board_and_section(
    running_http_hub, monkeypatch, tmp_path
):
    base_url, app = running_http_hub
    calls = []

    def get_board(board_id, *, section=None):
        calls.append((board_id, section))
        return {"success": True, "board_id": board_id, "section": section, "content": "value"}

    monkeypatch.setattr(app, "agent_blackboard", SimpleNamespace(get=get_board))
    url = f"{base_url}/api/agent-state/blackboard?board_id=task-31&task_id=task-31&section=plan&root={quote(str(tmp_path))}"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with _urlopen_with_error_body(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/agent-state/blackboard?board_id=task-31&task_id=task-31&section=plan&root={quote(str(tmp_path))}"
    assert status == 200
    assert calls == [("task-31", "plan")]
    assert result["success"] is True
    assert result["content"] == "value"


def test_http_post_declaration_not_found_returns_http_404(
    running_http_hub, monkeypatch, tmp_path
):
    base_url, app = running_http_hub
    monkeypatch.setattr(
        app.services,
        "code_find_declaration",
        lambda *args, **kwargs: {
            "success": False,
            "status_code": 404,
            "terminal": True,
            "retryable": False,
            "error_code": "declaration_not_found",
            "error": "Declaration of 'missing_symbol' not found",
        },
    )
    request = urllib_request.Request(
        f"{base_url}/api/code/declaration",
        data=json.dumps({"root": str(tmp_path), "symbol": "missing_symbol"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with pytest.raises(HTTPError) as exc_info:
        urllib_request.urlopen(request)

    assert exc_info.value.code == 404
    body = json.loads(exc_info.value.read().decode("utf-8"))
    assert body == {
        "success": False,
        "status_code": 404,
        "terminal": True,
        "retryable": False,
        "error_code": "declaration_not_found",
        "error": "Declaration of 'missing_symbol' not found",
        "request_id": body["request_id"],
    }


def test_http_get_declaration_not_found_returns_http_404(
    running_http_hub, monkeypatch, tmp_path
):
    base_url, app = running_http_hub
    monkeypatch.setattr(
        app.services,
        "code_find_declaration",
        lambda *args, **kwargs: {
            "success": False,
            "status_code": 404,
            "terminal": True,
            "retryable": False,
            "error_code": "declaration_not_found",
            "error": "Declaration of 'missing_symbol' not found",
        },
    )
    request = urllib_request.Request(
        f"{base_url}/api/code/find_declaration?root={quote(str(tmp_path))}&symbol=missing_symbol",
        headers={},
        method="GET",
    )

    with pytest.raises(HTTPError) as exc_info:
        urllib_request.urlopen(request)

    assert exc_info.value.code == 404
    body = json.loads(exc_info.value.read().decode("utf-8"))
    assert body["success"] is False
    assert body["status_code"] == 404
    assert body["terminal"] is True
    assert body["retryable"] is False
    assert body["error_code"] == "declaration_not_found"


def test_http_patch_validate_returns_successful_result_for_invalid_diff(
    running_http_hub, tmp_path
):
    base_url, _app = running_http_hub
    request = urllib_request.Request(
        f"{base_url}/api/patch/validate",
        data=json.dumps({"root": str(tmp_path), "patch": "not a unified diff"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib_request.urlopen(request) as response:
        body = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert body["success"] is True
    assert body["valid"] is False
    assert body["syntax_valid"] is False
    assert body["applicability_checked"] is False
    assert "patch changes no files" in body["errors"]


def test_http_patch_validate_rejects_empty_patch_as_bad_request(
    running_http_hub, tmp_path
):
    base_url, _app = running_http_hub
    request = urllib_request.Request(
        f"{base_url}/api/patch/validate",
        data=json.dumps({"root": str(tmp_path), "patch": "  "}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with pytest.raises(HTTPError) as exc_info:
        urllib_request.urlopen(request)

    assert exc_info.value.code == 400
    body = json.loads(exc_info.value.read().decode("utf-8"))
    assert body["success"] is False
    assert body["status_code"] == 400
    assert body["terminal"] is True
    assert body["retryable"] is False
    assert body["error_code"] == "patch_required"


def test_http_git_diff_forwards_current_revision_contract(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []

    def git_diff(root, *, path=None, staged=False, max_lines=1000, rev1=None, rev2=None):
        calls.append((root, path, staged, max_lines, rev1, rev2))
        return {"success": True, "diff": "bounded diff"}

    monkeypatch.setattr(app.services, "git_diff", git_diff)
    query = (
        f"root={quote(str(tmp_path))}&path={quote('src/example.py')}"
        "&staged=false&max_lines=25&base=HEAD"
    )
    request = urllib_request.Request(
        f"{base_url}/api/git/diff?{query}",
        headers={},
        method="GET",
    )

    with _urlopen_with_error_body(request) as response:
        result = json.loads(response.read().decode("utf-8"))

    assert calls == [(str(tmp_path), "src/example.py", False, 25, None, None)]
    assert result["success"] is True
    assert result["diff"] == "bounded diff"


def test_http_git_diff_post_forwards_revision_pair_without_base_alias(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []

    def git_diff(root, *, path=None, staged=False, max_lines=1000, rev1=None, rev2=None):
        calls.append((root, path, staged, max_lines, rev1, rev2))
        return {"success": True, "diff": "bounded diff"}

    monkeypatch.setattr(app.services, "git_diff", git_diff)
    payload = {"root": str(tmp_path), "path": "src/example.py", "staged": False,
               "max_lines": 25, "rev1": "HEAD~1", "rev2": "HEAD", "base": "HEAD~1", "head": "HEAD"}
    request = urllib_request.Request(
        f"{base_url}/api/git/diff", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with _urlopen_with_error_body(request) as response:
        result = json.loads(response.read().decode("utf-8"))

    assert calls == [(str(tmp_path), "src/example.py", False, 25, "HEAD~1", "HEAD")]
    assert result["success"] is True

    payload.pop("rev1")
    payload.pop("rev2")
    request = urllib_request.Request(
        f"{base_url}/api/git/diff", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with _urlopen_with_error_body(request) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert calls[-1] == (str(tmp_path), "src/example.py", False, 25, "HEAD~1", "HEAD")
    assert result["success"] is True

    payload.update(base="HEAD", head="HEAD~1")
    request = urllib_request.Request(
        f"{base_url}/api/git/diff", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with _urlopen_with_error_body(request) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert calls[-1] == (str(tmp_path), "src/example.py", False, 25, "HEAD", "HEAD~1")
    assert result["success"] is True

    payload.update(base="HEAD~1", head="HEAD", rev1="HEAD~2", rev2="HEAD")
    request = urllib_request.Request(
        f"{base_url}/api/git/diff", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with pytest.raises(HTTPError) as exc:
        urllib_request.urlopen(request)
    assert exc.value.code == 400
    exc.value.close()
    assert len(calls) == 3


def test_http_git_diff_post_compares_actual_revisions(running_http_hub, tmp_path):
    base_url, _app = running_http_hub
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
            cwd=repo, check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    git("init")
    target = repo / "example.txt"
    target.write_text("before\n", encoding="utf-8")
    git("add", "example.txt")
    git("commit", "-m", "first")
    first = git("rev-parse", "HEAD")
    target.write_text("after\n", encoding="utf-8")
    git("commit", "-am", "second")
    second = git("rev-parse", "HEAD")
    payload = {"root": str(repo), "rev1": first, "rev2": second, "base": "HEAD", "head": second}
    request = urllib_request.Request(
        f"{base_url}/api/git/diff", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with _urlopen_with_error_body(request) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True
    assert result["resolved_rev1"] == first
    assert result["resolved_rev2"] == second
    assert "-before" in result["diff"] and "+after" in result["diff"]


def test_http_rag_search_cannot_bypass_reranker_capability_gate(
    running_http_hub, monkeypatch, tmp_path
):
    base_url, app = running_http_hub
    calls = []

    def search(query, **kwargs):
        calls.append((query, kwargs))
        return {"success": True, "results": []}

    monkeypatch.setattr(app.rag, "require_workspace_root", lambda **_kwargs: None)
    monkeypatch.setattr(app.rag, "search", search)
    monkeypatch.setitem(
        app.config,
        "features",
        {**app.config.get("features", {}), "local_reranking": False},
    )
    monkeypatch.setitem(app.config, "hardware", {**app.config.get("hardware", {}), "profile": "low"})
    monkeypatch.setitem(app.config, "_hardware", {"profile": "low"})
    root = str(tmp_path.resolve())
    payload = {
        "root": root,
        "workspace": "project:test",
        "query": "needle",
        "top_k": 6,
        "use_reranker": True,
    }
    request = urllib_request.Request(
        f"{base_url}/api/rag/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with _urlopen_with_error_body(request) as response:
        result = json.loads(response.read().decode("utf-8"))

    assert result["success"] is True
    assert calls == [(
        "needle",
        {"workspace": "project:test", "top_k": 6, "use_reranker": False, "semantic_only": True},
    )]


def test_http_get_agent_state_events_forwards_stream_cursor_and_limit(
    running_http_hub, monkeypatch, tmp_path
):
    base_url, app = running_http_hub
    calls = []
    event = SimpleNamespace(
        to_dict=lambda: {"seq": 8, "kind": "task.updated", "stream_id": "stream-31"}
    )

    def event_page(*, stream_id="", after_seq=0, limit=100, through_seq=None):
        calls.append((stream_id, int(after_seq), limit))
        return {
            "success": True,
            "events": [event.to_dict()],
            "next_seq": 8,
            "first_retained_seq": 1,
            "last_seq": 8,
            "has_more": False,
            "gap_ranges": [],
            "cursor_reset": False,
            "error": None,
        }

    monkeypatch.setattr(app.agent_state, "event_page", event_page)
    url = f"{base_url}/api/agent-state/events?stream_id=task%3Atask-31&after_seq=4&limit=9&root={quote(str(tmp_path))}"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with _urlopen_with_error_body(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/agent-state/events?stream_id=task%3Atask-31&after_seq=4&limit=9&root={quote(str(tmp_path))}"
    assert status == 200
    assert calls == [("task:task-31", 4, 9)]
    assert result["success"] is True
    assert result["events"] == [{"seq": 8, "kind": "task.updated", "stream_id": "stream-31"}]


def test_http_get_agent_state_tasks_forwards_filters_and_serializes(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []
    task = SimpleNamespace(
        task_id="task-77",
        context=ScopeContext(repository_id=str(tmp_path.resolve()), session_id="session:http-route-acceptance"),
        checkpoint=SimpleNamespace(
            state_data={
                "_agent_task_scope": {
                    "version": 2,
                    "repo_root": str(tmp_path.resolve()),
                }
            }
        ),
        to_dict=lambda: {"task_id": "task-77", "status": "active", "summary": "T08 task"}
    )

    def list_tasks(*, status=None, limit=100, offset=0, include_stale=False, query=""):
        calls.append((getattr(status, "value", status), limit, offset, include_stale, query))
        return [task]

    monkeypatch.setattr(app.agent_tasks, "list_tasks", list_tasks)
    url = f"{base_url}/api/agent-state/tasks?status=active&limit=7&offset=3&include_stale=true&root={quote(str(tmp_path))}"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with _urlopen_with_error_body(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/agent-state/tasks?status=active&limit=7&offset=3&include_stale=true&root={quote(str(tmp_path))}"
    assert status == 200
    assert calls == [("active", 8, 3, True, "")]
    assert result["offset"] == 3 and result["limit"] == 7
    assert result["next_offset"] == 4 and result["has_more"] is False
    assert result["success"] is True
    assert result["tasks"] == [{"task_id": "task-77", "status": "active", "summary": "T08 task"}]


def test_http_post_agent_state_cleanup_forwards_retention_policy(running_http_hub, monkeypatch):
    base_url, app = running_http_hub
    calls = []
    response_data = {"success": True, "retention_days": 21, "deleted_events": 0}

    def cleanup(*, retention_days):
        calls.append(retention_days)
        return response_data

    monkeypatch.setattr(app.agent_state, "cleanup", cleanup)
    url = f"{base_url}/api/agent-state/cleanup"
    request = urllib_request.Request(
        url,
        data=json.dumps({"retention_days": 21}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "POST"
    assert url == f"{base_url}/api/agent-state/cleanup"
    assert status == 200
    assert calls == [21]
    assert result == {**response_data, "request_id": result.get("request_id")}
    assert isinstance(result["request_id"], str) and result["request_id"]


def test_http_post_agent_state_swarm_dispatch_forwards_explicit_scope(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []
    response_data = {"success": True, "swarm_id": "swarm-21", "state": "queued"}

    def dispatch(*, goal, target_paths, test_command, author, root):
        calls.append({
            "goal": goal,
            "target_paths": target_paths,
            "test_command": test_command,
            "author": author,
            "root": root,
        })
        return response_data

    monkeypatch.setattr(app.swarm, "dispatch", dispatch)
    payload = {
        "goal": "Audit the selected route contract",
        "target_paths": ["src/local_ai_hub/http_server.py", "tests/test_http_route_operation_acceptance.py"],
        "test_command": "pytest -q tests/test_http_route_operation_acceptance.py::test_route",
        "author": "acceptance-test",
        "root": str(tmp_path),
    }
    url = f"{base_url}/api/agent-state/swarm/dispatch"
    request = urllib_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "POST"
    assert url == f"{base_url}/api/agent-state/swarm/dispatch"
    assert status == 200
    assert calls == [payload]
    assert result == {**response_data, "request_id": result.get("request_id")}
    assert isinstance(result["request_id"], str) and result["request_id"]


def test_http_get_agent_state_swarm_forwards_state_and_limit(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []

    def list_swarms(*, state=None, limit=50, root=None):
        calls.append((state, limit, root))
        return {"success": True, "swarms": [{"swarm_id": "swarm-31", "state": state}]}

    monkeypatch.setattr(app, "swarm", SimpleNamespace(list_swarms=list_swarms))
    url = f"{base_url}/api/agent-state/swarm?state=running&limit=6&root={quote(str(tmp_path))}"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/agent-state/swarm?state=running&limit=6&root={quote(str(tmp_path))}"
    assert status == 200
    assert calls == [("running", 6, str(tmp_path.resolve()))]
    assert result["swarms"] == [{"swarm_id": "swarm-31", "state": "running"}]


def test_http_get_agent_state_swarm_detail_forwards_swarm_id(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []

    def get_status(swarm_id, *, root=None):
        calls.append((swarm_id, root))
        return {"success": True, "swarm_id": swarm_id, "step": 3}

    monkeypatch.setattr(app, "swarm", SimpleNamespace(get_status=get_status))
    url = f"{base_url}/api/agent-state/swarm/swarm-31?root={quote(str(tmp_path))}"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/agent-state/swarm/swarm-31?root={quote(str(tmp_path))}"
    assert status == 200
    assert calls == [("swarm-31", str(tmp_path.resolve()))]
    assert result["swarm_id"] == "swarm-31"
    assert result["step"] == 3


def test_http_get_config_contains_no_retired_token_setting(running_http_hub):
    base_url, _app = running_http_hub
    url = f"{base_url}/api/config"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/config"
    assert status == 200
    assert result["success"] is True
    assert "api_token" not in result["config"]["security"]


def test_http_get_capabilities_returns_surface_and_features(running_http_hub):
    base_url, _app = running_http_hub
    url = f"{base_url}/api/capabilities"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/capabilities"
    assert status == 200
    assert result["success"] is True
    assert result["mcp_surface"] == "compact"
    assert "features" in result


def test_http_get_audit_tail_forwards_limit(running_http_hub, monkeypatch):
    base_url, app = running_http_hub
    monkeypatch.setattr(app.debug_traces, "enabled", True)
    calls = []

    def tail(limit):
        calls.append(limit)
        return [{"kind": "request.completed", "seq": 31}]

    monkeypatch.setattr(app.telemetry, "tail", tail)
    url = f"{base_url}/api/audit/tail?limit=3"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/audit/tail?limit=3"
    assert status == 200
    assert calls == [3]
    assert result["events"] == [{"kind": "request.completed", "seq": 31}]


def test_http_get_audit_dependencies_forwards_root(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []

    def audit_dependencies(root):
        calls.append(root)
        return {"success": True, "root": root, "issues": ["missing-import"]}

    monkeypatch.setattr(
        app, "deterministic", SimpleNamespace(audit_dependencies=audit_dependencies)
    )
    url = f"{base_url}/api/audit_dependencies?root={quote(str(tmp_path))}"
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/audit_dependencies?root={quote(str(tmp_path))}"
    assert status == 200
    assert calls == [str(tmp_path)]
    assert result["issues"] == ["missing-import"]


def test_http_get_affected_tests_forwards_root_and_repeated_paths(
    running_http_hub, monkeypatch, tmp_path
):
    base_url, app = running_http_hub
    calls = []

    def affected_tests(root, *, changed_paths=None):
        calls.append((root, changed_paths))
        return {"success": True, "affected": ["tests/test_routes.py"]}

    monkeypatch.setattr(app, "deterministic", SimpleNamespace())
    monkeypatch.setattr(app.services, "affected_tests", affected_tests)
    url = (
        f"{base_url}/api/repo/affected_tests?root={quote(str(tmp_path))}"
        "&path=src%2Fhttp_server.py&path=tests%2Ftest_routes.py"
    )
    request = urllib_request.Request(
        url, headers={}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == (
        f"{base_url}/api/repo/affected_tests?root={quote(str(tmp_path))}"
        "&path=src%2Fhttp_server.py&path=tests%2Ftest_routes.py"
    )
    assert status == 200
    assert calls == [(str(tmp_path), ["src/http_server.py", "tests/test_routes.py"])]
    assert result["affected"] == ["tests/test_routes.py"]


def test_http_post_affected_tests_forwards_json_paths(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []

    def affected_tests(root, *, changed_paths=None):
        calls.append((root, changed_paths))
        return {"success": True, "affected": ["tests/test_agent_state.py"]}

    monkeypatch.setattr(app, "deterministic", SimpleNamespace())
    monkeypatch.setattr(app.services, "affected_tests", affected_tests)
    body = json.dumps(
        {
            "root": str(tmp_path),
            "paths": ["src/agent_state.py"],
        }
    ).encode("utf-8")
    url = f"{base_url}/api/repo/affected_tests"
    request = urllib_request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "POST"
    assert url == f"{base_url}/api/repo/affected_tests"
    assert status == 200
    assert calls == [(str(tmp_path), ["src/agent_state.py"])]
    assert result["success"] is True
    assert result["affected"] == ["tests/test_agent_state.py"]


def test_http_post_agent_state_tasks_captures_laya_candidate_without_echoing_state(
    running_http_hub, tmp_path
):
    base_url, app = running_http_hub
    candidate_state = "synthetic model-route state for HTTP contract verification"
    url = f"{base_url}/api/agent-state/tasks"

    def post(operation):
        body = json.dumps(
            {
                "action": "curate_dataset",
                "root": str(tmp_path),
                "laya_operation": operation,
            }
        ).encode("utf-8")
        request = urllib_request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urlopen_with_error_body(request) as response:
            assert response.status == 200
            return json.loads(response.read().decode("utf-8"))

    capture_operation = {
        "action": "capture",
        "task_id": "task-31",
        "session_id": "session:http-route-acceptance",
        "candidate": {
            "decision_schema_version": "laya-hub-v1",
            "category": "model_route",
            "state": candidate_state,
            "options": ["fast", "smart", "background"],
            "language": "en",
            "preprocessing": {"name": "none", "version": "1"},
            "evidence_ids": ["ev-http-test"],
        },
    }
    denied_request = urllib_request.Request(
        url,
        data=json.dumps(
            {
                "action": "curate_dataset",
                "root": str(tmp_path),
                "laya_operation": capture_operation,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as denied:
        urllib_request.urlopen(denied_request)
    assert denied.value.code == 409
    denied_body = json.loads(denied.value.read().decode("utf-8"))
    assert denied_body["error_code"] == "detailed_diagnostics_disabled"
    assert app.laya_candidates.handle(
        {"action": "list", "task_id": "task-31"},
        root=str(tmp_path),
        task_store=app.agent_tasks,
    )["count"] == 0

    toggle_request = urllib_request.Request(
        f"{base_url}/api/config/update",
        data=json.dumps({"settings": {"debug_traces.enabled": True}}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _urlopen_with_error_body(toggle_request) as response:
        assert response.status == 200
        toggled = json.loads(response.read().decode("utf-8"))
    assert toggled["success"] is True

    request = urllib_request.Request(
        url,
        data=json.dumps({
            "action": "curate_dataset", "root": str(tmp_path), "laya_operation": capture_operation,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as denied_capture:
        urllib_request.urlopen(request)
    assert denied_capture.value.code == 400
    body = json.loads(denied_capture.value.read().decode("utf-8"))
    assert "actual Laya runtime callback" in body["error"]
    assert candidate_state not in json.dumps(body)
    assert app.laya_candidates.handle(
        {"action": "list", "task_id": "task-31"},
        root=str(tmp_path),
        task_store=app.agent_tasks,
    )["count"] == 0


def test_http_diagnostics_export_rejects_retired_laya_consent_and_forwards_snapshot_scope(
    running_http_hub, tmp_path, monkeypatch
):
    base_url, app = running_http_hub
    url = f"{base_url}/api/diagnostics/export"
    toggle_request = urllib_request.Request(
        f"{base_url}/api/config/update",
        data=json.dumps({"settings": {"debug_traces.enabled": True}}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _urlopen_with_error_body(toggle_request) as response:
        assert response.status == 200
        assert json.loads(response.read().decode("utf-8"))["success"] is True

    archive_path = tmp_path / "synthetic-diagnostics.zip"
    archive_bytes = b"synthetic encrypted zip bytes"
    archive_path.write_bytes(archive_bytes)
    closed = threading.Event()
    export = SimpleNamespace(
        path=archive_path,
        size=len(archive_bytes),
        manifest={"included_files": 1},
        password="synthetic-export-password",
        close=closed.set,
    )
    calls = []

    def export_diagnostics(*, cancelled, candidate_export):
        calls.append((cancelled, candidate_export))
        return export

    monkeypatch.setattr(app, "export_diagnostics", export_diagnostics)

    denied_request = urllib_request.Request(
        url,
        data=json.dumps(
            {
                "root": str(tmp_path),
                "laya_candidate_export": {
                    "consent": False,
                    "snapshot_id": "snapshot-test",
                },
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as denied:
        urllib_request.urlopen(denied_request)
    assert denied.value.code == 400
    denied_body = json.loads(denied.value.read().decode("utf-8"))
    assert denied_body["error_code"] == "diagnostics_export_request_invalid"
    assert calls == []

    request = urllib_request.Request(
        url,
        data=json.dumps(
            {
                "root": str(tmp_path),
                "laya_candidate_export": {
                    "snapshot_id": "snapshot-test",
                },
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(request) as response:
        assert response.status == 200
        assert response.read() == archive_bytes

    assert len(calls) == 1
    assert callable(calls[0][0])
    assert calls[0][1] == {
        "root": str(tmp_path),
        "laya_candidate_export": {
            "snapshot_id": "snapshot-test",
        },
    }
    assert closed.wait(timeout=1.0)


def test_http_diagnostics_export_preserves_request_body_timeout_status(
    running_http_hub, monkeypatch
):
    base_url, _app = running_http_hub

    def timeout_body(_handler):
        raise http_server.RequestBodyError("request body timed out", 408)

    monkeypatch.setattr(http_server.Handler, "_read_json", timeout_body)
    request = urllib_request.Request(
        f"{base_url}/api/diagnostics/export",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with pytest.raises(HTTPError) as timeout:
        urllib_request.urlopen(request)

    assert timeout.value.code == 408
    body = json.loads(timeout.value.read().decode("utf-8"))
    assert body["success"] is False
    assert body["error"] == "request body timed out"


def test_http_post_coord_plan_routes_acceptance(running_http_hub, tmp_path):
    base_url, app = running_http_hub

    # 1. /api/coord/plan_create: test cross-root containment (fail closed)
    outside_root = tmp_path.parent / "outside"
    req_cross = urllib_request.Request(
        f"{base_url}/api/coord/plan_create",
        data=json.dumps({"root": str(outside_root), "title": "Bad Plan"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc_cross:
        urllib_request.urlopen(req_cross)
    exc_cross.value.close()
    assert exc_cross.value.code in (400, 403)

    # Valid plan_create with task_1
    req_create = urllib_request.Request(
        f"{base_url}/api/coord/plan_create",
        data=json.dumps({
            "root": str(tmp_path),
            "title": "Acceptance Plan",
            "plan_id": "plan_acceptance_test",
            "tasks": {"task_1": {"title": "Task 1", "work_status": "planned"}},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_create) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert res["success"] is True
        assert res["plan_id"] == "plan_acceptance_test"
        rev = res.get("file_revision") or ""

    # 2. /api/coord/plan_task_edit: cross-root containment
    req_edit_cross = urllib_request.Request(
        f"{base_url}/api/coord/plan_task_edit",
        data=json.dumps({
            "root": str(outside_root),
            "plan_id": "plan_acceptance_test",
            "task_id": "task_1",
            "expected_revision": rev or "rev1",
            "task_data": {"title": "Task 1", "work_status": "in_progress"},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc_edit_cross:
        urllib_request.urlopen(req_edit_cross)
    exc_edit_cross.value.close()
    assert exc_edit_cross.value.code in (400, 403)

    # Valid plan_task_edit
    req_edit = urllib_request.Request(
        f"{base_url}/api/coord/plan_task_edit",
        data=json.dumps({
            "root": str(tmp_path),
            "plan_id": "plan_acceptance_test",
            "task_id": "task_1",
            "expected_revision": rev,
            "task_data": {"title": "Task 1 Updated", "work_status": "planned"},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_edit) as resp:
        assert resp.status == 200
        res_edit = json.loads(resp.read().decode("utf-8"))
        assert res_edit["success"] is True
        rev2 = res_edit.get("file_revision") or rev

    # 3. /api/coord/plan_task_delete: cross-root containment
    req_del_cross = urllib_request.Request(
        f"{base_url}/api/coord/plan_task_delete",
        data=json.dumps({
            "root": str(outside_root),
            "plan_id": "plan_acceptance_test",
            "task_id": "task_1",
            "expected_revision": rev2,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc_del_cross:
        urllib_request.urlopen(req_del_cross)
    exc_del_cross.value.close()
    assert exc_del_cross.value.code in (400, 403)

    # Valid plan_task_delete
    req_del = urllib_request.Request(
        f"{base_url}/api/coord/plan_task_delete",
        data=json.dumps({
            "root": str(tmp_path),
            "plan_id": "plan_acceptance_test",
            "task_id": "task_1",
            "expected_revision": rev2,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_del) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert res["success"] is True


def test_http_post_complete_acceptance(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    monkeypatch.setattr(
        app.services,
        "complete_code",
        lambda payload: {"success": True, "completed": True, "text": "result_code"},
    )
    req = urllib_request.Request(
        f"{base_url}/api/complete",
        data=json.dumps({"prompt": "def hello():", "root": str(tmp_path)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert res["success"] is True
        assert res["text"] == "result_code"


def test_http_post_worktree_routes_acceptance(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    outside_root = tmp_path.parent / "outside"

    req_lease_bad = urllib_request.Request(
        f"{base_url}/api/coord/worktree_lease",
        data=json.dumps({"root": str(outside_root)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc:
        urllib_request.urlopen(req_lease_bad)
    exc.value.close()
    assert exc.value.code in (400, 403)

    req_rel_bad = urllib_request.Request(
        f"{base_url}/api/coord/worktree_release",
        data=json.dumps({"root": str(outside_root)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc:
        urllib_request.urlopen(req_rel_bad)
    exc.value.close()
    assert exc.value.code in (400, 403)

    monkeypatch.setattr(
        app.services,
        "worktree_lease",
        lambda root, branch_name=None: {"success": True, "branch": "test-branch", "path": str(tmp_path / "wt")},
    )
    monkeypatch.setattr(
        app.services,
        "worktree_release",
        lambda *args, **kwargs: {"success": True, "released": True},
    )
    req_lease = urllib_request.Request(
        f"{base_url}/api/coord/worktree_lease",
        data=json.dumps({"root": str(tmp_path), "branch": "test-branch"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_lease) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True

    req_rel = urllib_request.Request(
        f"{base_url}/api/coord/worktree_release",
        data=json.dumps({"root": str(tmp_path), "worktree_path": str(tmp_path / "wt")}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_rel) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True


def test_http_post_repo_patch_acceptance(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    outside_root = tmp_path.parent / "outside"

    req_bad = urllib_request.Request(
        f"{base_url}/api/repo/patch",
        data=json.dumps({"root": str(outside_root), "path": "file.txt", "old_code": "a", "new_code": "b"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc:
        urllib_request.urlopen(req_bad)
    exc.value.close()
    assert exc.value.code in (400, 403)

    monkeypatch.setattr(
        app.repo_tools,
        "apply_patch",
        lambda root, path, old, new: {"success": True, "applied": True, "path": path},
    )
    req_good = urllib_request.Request(
        f"{base_url}/api/repo/patch",
        data=json.dumps({"root": str(tmp_path), "path": "file.txt", "old_code": "a", "new_code": "b"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_good) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True


def test_http_post_coord_board_and_semaphore_acceptance(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub

    # 1. Semaphore release
    monkeypatch.setattr(
        app.services,
        "semaphore_release",
        lambda name="", lease_id="", owner="": {"success": True, "released": True},
    )
    req_sem = urllib_request.Request(
        f"{base_url}/api/coord/semaphore_release",
        data=json.dumps({"name": "gpu_sem", "lease_id": "l-1", "owner": "test"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_sem) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True

    # 2. Board item create & delete
    monkeypatch.setattr(
        app.services,
        "board_item_create",
        lambda **kwargs: {"success": True, "item_id": "item-1"},
    )
    monkeypatch.setattr(
        app.services,
        "board_item_delete",
        lambda item_id="": {"success": True, "deleted": True},
    )
    req_create = urllib_request.Request(
        f"{base_url}/api/coord/board_item_create",
        data=json.dumps({"title": "Test Item", "root": str(tmp_path)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_create) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True

    req_delete = urllib_request.Request(
        f"{base_url}/api/coord/board_item_delete",
        data=json.dumps({"item_id": "item-1"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_delete) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True

    # 3. Milestone create
    monkeypatch.setattr(
        app.services,
        "milestone_create",
        lambda name="", target_date="", description="": {"success": True, "milestone": name},
    )
    req_m = urllib_request.Request(
        f"{base_url}/api/coord/milestone_create",
        data=json.dumps({"name": "v6.0", "target_date": "2026-11-15"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_m) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True


def test_http_post_context_budget_acceptance(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    outside_root = tmp_path.parent / "outside"

    req_bad = urllib_request.Request(
        f"{base_url}/api/repo/context_budget",
        data=json.dumps({"root": str(outside_root)}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc:
        urllib_request.urlopen(req_bad)
    exc.value.close()
    assert exc.value.code in (400, 403)

    monkeypatch.setattr(
        app.services,
        "context_budget",
        lambda root, files=None, max_tokens=4000: {"success": True, "budget_tokens": max_tokens, "files": []},
    )
    req_good = urllib_request.Request(
        f"{base_url}/api/repo/context_budget",
        data=json.dumps({"root": str(tmp_path), "max_tokens": 8000}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_good) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True


def test_http_post_rag_ingest_acceptance(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    outside_root = tmp_path.parent / "outside"

    req_doc_bad = urllib_request.Request(
        f"{base_url}/api/rag/ingest_document",
        data=json.dumps({"root": str(outside_root), "content": "text"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc:
        urllib_request.urlopen(req_doc_bad)
    exc.value.close()
    assert exc.value.code in (400, 403)

    req_dia_bad = urllib_request.Request(
        f"{base_url}/api/rag/ingest_diagram",
        data=json.dumps({"root": str(outside_root), "image_path": "diag.png"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with pytest.raises(HTTPError) as exc:
        urllib_request.urlopen(req_dia_bad)
    exc.value.close()
    assert exc.value.code in (400, 403)

    monkeypatch.setattr(
        app.rag,
        "ingest_document",
        lambda **kwargs: {"success": True, "document_id": "doc-test", "chunks": 1},
    )
    monkeypatch.setattr(
        app.rag,
        "ingest_diagram",
        lambda **kwargs: {"success": True, "diagram_id": "dia-test"},
    )
    req_doc = urllib_request.Request(
        f"{base_url}/api/rag/ingest_document",
        data=json.dumps({"root": str(tmp_path), "content": "valid text content", "title": "Doc 1"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_doc) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True

    req_dia = urllib_request.Request(
        f"{base_url}/api/rag/ingest_diagram",
        data=json.dumps({"root": str(tmp_path), "image_path": "diag.png", "caption": "Diagram 1"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Connection": "close"},
        method="POST",
    )
    with urllib_request.urlopen(req_dia) as resp:
        assert resp.status == 200
        assert json.loads(resp.read().decode("utf-8"))["success"] is True
