"""Operation-level HTTP acceptance for selected unlinked route families."""

from __future__ import annotations

import json
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


def _root_tenant(root):
    return http_server._derive_root_tenant(
        "tenant-acceptance",
        str(root),
        "tenant-derivation-test-key-0123456789abcdef",
    )


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
                'api_token = "acceptance-secret"',
                'api_token_tenant = "tenant-acceptance"',
                f'allowed_roots = ["{tmp_path.as_posix()}"]',
                'tenant_derivation_key = "tenant-derivation-test-key-0123456789abcdef"',
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
            session_id=_root_tenant(tmp_path),
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
    url = f"{base_url}/api/agent-state/blackboard?board_id=task-31&task_id=task-31&section=plan&root={quote(str(tmp_path))}&tenant={quote(_root_tenant(tmp_path))}"
    request = urllib_request.Request(
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
    )

    with _urlopen_with_error_body(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/agent-state/blackboard?board_id=task-31&task_id=task-31&section=plan&root={quote(str(tmp_path))}&tenant={quote(_root_tenant(tmp_path))}"
    assert status == 200
    assert calls == [("task-31", "plan")]
    assert result["success"] is True
    assert result["content"] == "value"


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
    url = f"{base_url}/api/agent-state/events?stream_id=task%3Atask-31&after_seq=4&limit=9&root={quote(str(tmp_path))}&tenant={quote(_root_tenant(tmp_path))}"
    request = urllib_request.Request(
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
    )

    with _urlopen_with_error_body(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/agent-state/events?stream_id=task%3Atask-31&after_seq=4&limit=9&root={quote(str(tmp_path))}&tenant={quote(_root_tenant(tmp_path))}"
    assert status == 200
    assert calls == [("task:task-31", 4, 9)]
    assert result["success"] is True
    assert result["events"] == [{"seq": 8, "kind": "task.updated", "stream_id": "stream-31"}]


def test_http_get_agent_state_tasks_forwards_filters_and_serializes(running_http_hub, monkeypatch, tmp_path):
    base_url, app = running_http_hub
    calls = []
    task = SimpleNamespace(
        context=ScopeContext(repository_id=str(tmp_path), session_id=_root_tenant(tmp_path)),
        to_dict=lambda: {"task_id": "task-77", "status": "active", "summary": "T08 task"}
    )

    def list_tasks(*, status=None, limit=100, include_stale=False, query=""):
        calls.append((getattr(status, "value", status), limit, include_stale, query))
        return [task]

    monkeypatch.setattr(app.agent_tasks, "list_tasks", list_tasks)
    url = f"{base_url}/api/agent-state/tasks?status=active&limit=7&include_stale=true&root={quote(str(tmp_path))}&tenant={quote(_root_tenant(tmp_path))}"
    request = urllib_request.Request(
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
    )

    with _urlopen_with_error_body(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/agent-state/tasks?status=active&limit=7&include_stale=true&root={quote(str(tmp_path))}&tenant={quote(_root_tenant(tmp_path))}"
    assert status == 200
    assert calls == [("active", 7, True, "")]
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
        headers={"X-LocalAI-Token": "acceptance-secret", "Content-Type": "application/json"},
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
        headers={"X-LocalAI-Token": "acceptance-secret", "Content-Type": "application/json"},
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
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
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
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
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


def test_http_get_config_redacts_configured_token(running_http_hub):
    base_url, _app = running_http_hub
    url = f"{base_url}/api/config"
    request = urllib_request.Request(
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/config"
    assert status == 200
    assert result["success"] is True
    assert result["config"]["security"]["api_token"] == "***configured***"


def test_http_get_capabilities_returns_surface_and_features(running_http_hub):
    base_url, _app = running_http_hub
    url = f"{base_url}/api/capabilities"
    request = urllib_request.Request(
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
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
    calls = []

    def tail(limit):
        calls.append(limit)
        return [{"kind": "request.completed", "seq": 31}]

    monkeypatch.setattr(app.telemetry, "tail", tail)
    url = f"{base_url}/api/audit/tail?limit=3"
    request = urllib_request.Request(
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
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
    url = f"{base_url}/api/audit_dependencies?root={quote(str(tmp_path))}&tenant={quote(_root_tenant(tmp_path))}"
    request = urllib_request.Request(
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == f"{base_url}/api/audit_dependencies?root={quote(str(tmp_path))}&tenant={quote(_root_tenant(tmp_path))}"
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
        f"{base_url}/api/affected_tests?root={quote(str(tmp_path))}"
        f"&tenant={quote(_root_tenant(tmp_path))}"
        "&path=src%2Fhttp_server.py&path=tests%2Ftest_routes.py"
    )
    request = urllib_request.Request(
        url, headers={"X-LocalAI-Token": "acceptance-secret"}, method="GET"
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "GET"
    assert url == (
        f"{base_url}/api/affected_tests?root={quote(str(tmp_path))}"
        f"&tenant={quote(_root_tenant(tmp_path))}"
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
            "tenant": _root_tenant(tmp_path),
            "paths": ["src/agent_state.py"],
        }
    ).encode("utf-8")
    url = f"{base_url}/api/affected_tests"
    request = urllib_request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-LocalAI-Token": "acceptance-secret",
        },
        method="POST",
    )

    with urllib_request.urlopen(request) as response:
        status = response.status
        result = json.loads(response.read().decode("utf-8"))

    assert request.get_method() == "POST"
    assert url == f"{base_url}/api/affected_tests"
    assert status == 200
    assert calls == [(str(tmp_path), ["src/agent_state.py"])]
    assert result["success"] is True
    assert result["affected"] == ["tests/test_agent_state.py"]
