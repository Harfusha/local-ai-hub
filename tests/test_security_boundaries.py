from local_ai_hub.command_broker import build_invocation, validate_invocation


from types import SimpleNamespace

from local_ai_hub import http_server
from local_ai_hub.agent_task_models import GoalContract, ScopeContext, TaskStatus
from local_ai_hub.command_broker import build_invocation, validate_invocation


def _create_test_handler(
    path: str = "/api/status",
    command: str = "GET",
    peer: str = "127.0.0.1",
    headers: dict[str, str] | None = None,
    config: dict | None = None,
):
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = path
    handler.command = command
    handler.headers = headers or {"Host": "127.0.0.1:11435"}
    if "Host" not in handler.headers:
        handler.headers["Host"] = "127.0.0.1:11435"
    handler.client_address = (peer, 34567)
    handler.server = SimpleNamespace(check_rate_limit=lambda: True)
    handler.responses = []
    handler._send = lambda status, payload: handler.responses.append((status, payload))
    handler._audit_admin_authorization = lambda *args, **kwargs: True
    http_server.APP = SimpleNamespace(
        config=config or {"server": {"bind": "127.0.0.1"}, "security": {}},
    )
    return handler


def test_raw_shell_expansion_is_not_accepted():
    result = validate_invocation("powershell -Command Write-Host $HOME")
    assert result["safe"] is False
    assert result["reason"] == "unstructured_shell_text"
    assert result["terminal"] is True


def test_shell_true_and_nul_are_rejected():
    assert validate_invocation({"argv": ["python", "-c", "print(1)"], "shell": True})["safe"] is False
    assert validate_invocation(["python", "bad\x00arg"])["reason"] == "nul_in_argv"


def test_unicode_and_spaces_stay_in_argv():
    invocation = build_invocation("python", ["-c", "print('žluťoučký a b')"], cwd="C:\\repo with space")
    assert invocation.argv == ["python", "-c", "print('žluťoučký a b')"]
    assert invocation.shell is False


def test_external_socket_peer_rejection():
    for external_ip in ("203.0.113.7", "192.168.1.100", "10.0.0.1", "172.16.0.5"):
        handler = _create_test_handler(peer=external_ip)
        assert handler._require_authorized() is False
        assert handler.responses
        status, payload = handler.responses[0]
        assert status == 403
        assert payload.get("success") is False


def test_spoofed_forwarded_headers_do_not_bypass_loopback_check():
    handler = _create_test_handler(
        peer="198.51.100.22",
        headers={
            "Host": "127.0.0.1:11435",
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
            "Client-IP": "127.0.0.1",
        },
    )
    assert handler._require_authorized() is False
    status, payload = handler.responses[0]
    assert status == 403
    assert payload.get("success") is False


def test_spoofed_actor_and_privilege_headers_are_rejected():
    for spoofed_header in ("X-LocalAI-Actor", "X-LocalAI-Role", "X-LocalAI-Permissions", "X-LocalAI-Privilege"):
        handler = _create_test_handler(
            path="/api/repo/state",
            command="GET",
            peer="127.0.0.1",
            headers={"Host": "127.0.0.1:11435", spoofed_header: "admin"},
        )
        assert handler._require_authorized() is False
        assert handler.responses
        status, payload = handler.responses[0]
        assert status == 400
        assert payload.get("error_code") == "spoofed_auth_header"


def test_cross_origin_browser_requests_are_rejected():
    # External Origin rejected
    handler_external = _create_test_handler(
        headers={"Host": "127.0.0.1:11435", "Origin": "http://evil.com"},
    )
    assert handler_external._require_authorized() is False
    assert handler_external.responses[0][0] == 403

    # Dashboard cross-site rejected
    handler_cross_site = _create_test_handler(
        headers={
            "Host": "127.0.0.1:11435",
            "X-LocalAI-Client": "dashboard",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert handler_cross_site._require_authorized() is False
    assert handler_cross_site.responses[0][0] == 403

    # Dashboard mutation without Origin rejected
    handler_no_origin_mut = _create_test_handler(
        command="POST",
        headers={
            "Host": "127.0.0.1:11435",
            "X-LocalAI-Client": "dashboard",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    assert handler_no_origin_mut._require_authorized() is False
    assert handler_no_origin_mut.responses[0][0] == 403


def test_unauthorized_agent_cannot_complete_other_agent_task(tmp_path):
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_tasks import TaskStore
    from local_ai_hub.http_post_tasks import handle_agent_state_tasks

    state_store = AgentStateStore(str(tmp_path / "state.db"))
    tasks = TaskStore(state_store)
    contract = GoalContract(goal="test task", acceptance_criteria=["criterion 1"])
    task = tasks.create(
        contract,
        ScopeContext(repository_id="repo-1", task_id="task-1"),
        task_id="task-1",
        actor="agent_alpha",
    )

    handler = _create_test_handler(command="POST", path="/api/agent-state/tasks")
    http_server.APP.agent_tasks = tasks
    handler.headers = {"Host": "127.0.0.1:11435", "X-LocalAI-Agent": "agent_beta"}
    handler._authorization_root = str(tmp_path)
    handler._request_task = lambda t_id, root: task

    # Attempt complete as agent_beta without allow_adopt
    payload = {"action": "complete", "task_id": task.task_id}
    handle_agent_state_tasks(handler, payload)

    assert handler.responses
    status, res = handler.responses[0]
    assert status == 403
    assert res.get("error_code") == "task_owner_mismatch"


def test_reserved_actor_cleanup_rejection(tmp_path):
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_task_models import TaskCheckpoint
    from local_ai_hub.agent_tasks import TaskStore

    state_store = AgentStateStore(str(tmp_path / "state.db"))
    tasks = TaskStore(state_store)
    contract = GoalContract(goal="test task", acceptance_criteria=["criterion 1"])
    task = tasks.create(
        contract,
        ScopeContext(repository_id="repo-1", task_id="task-2"),
        task_id="task-2",
        actor="normal_agent",
    )
    checkpoint = TaskCheckpoint(
        phase="work",
        state_data={"worktree": {"worktree_path": str(tmp_path / "wt"), "task_id": task.task_id}},
    )
    tasks.checkpoint(task.task_id, checkpoint, actor="normal_agent")

    for reserved in ("admin", "system", "*", "http-default", ""):
        res = tasks.cleanup_worktree(task.task_id, actor=reserved)
        assert res.get("success") is False
        assert "reserved owner actor" in res.get("error", "")

    # Mismatched actor rejection
    res_mismatch = tasks.cleanup_worktree(task.task_id, actor="attacker_agent")
    assert res_mismatch.get("success") is False
    assert "cleanup actor does not own task" in res_mismatch.get("error", "")

