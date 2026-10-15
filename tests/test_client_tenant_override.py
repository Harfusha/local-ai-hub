from __future__ import annotations

import json
import hashlib
import hmac
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

import pytest

import local_ai_hub.client as client_module
from local_ai_hub.client import HubClient


def _client(
    tmp_path: Path,
    *,
    tenant: str | None = "tenant-default",
    auto_start: bool = False,
    allowed_roots: list[Path] | None = None,
    security_overrides: dict[str, object] | None = None,
) -> HubClient:
    state_dir = tmp_path / "state"
    config_path = tmp_path / "hub.toml"
    security: dict[str, object] = {
        "api_token": "fallback-api-token",
        "api_token_tenant": "fixed-principal",
        "api_token_principal": "secondary-principal",
        "tenant_derivation_key": "configured-tenant-derivation-key-0123456789",
        "allowed_roots": allowed_roots or [tmp_path],
    }
    security.update(security_overrides or {})
    security_lines = ["[security]"]
    for key, value in security.items():
        if value is None:
            continue
        encoded = (
            "[" + ", ".join(json.dumps(item.as_posix()) for item in value) + "]"
            if key == "allowed_roots"
            else json.dumps(value)
        )
        security_lines.append(f"{key} = {encoded}")
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 39131\nstate_dir = "{state_dir.as_posix()}"\n'
        "[client]\nstartup_wait_seconds = 1\nstartup_poll_seconds = 0.01\n"
        + "\n".join(security_lines)
        + "\n",
        encoding="utf-8",
    )
    return HubClient(tenant=tenant, config_path=str(config_path), auto_start=auto_start)


def _expected_root_tenant(client: HubClient, root: Path) -> str:
    security = client.config["security"]
    configured = str(security.get("api_token_tenant", "") or "").strip()
    principal = configured or str(security.get("api_token_principal", "") or "").strip() or "api-token-default"
    key = str(security.get("tenant_derivation_key") or security.get("api_token") or "")
    canonical_root = str(root.resolve(strict=True))
    message = f"local-ai-root-tenant\0{principal}\0{canonical_root}".encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"root-{digest}"


def test_start_lock_identity_lookup_failure_uses_live_pid_fallback(tmp_path, monkeypatch):
    lock_path = tmp_path / "hub.start.lock"
    lock_path.write_text("123 1 test_start_id 7", encoding="ascii")
    monkeypatch.setattr(client_module, "process_identity", lambda _pid: None)
    monkeypatch.setattr(client_module, "pid_alive", lambda pid: pid == 123)

    assert client_module._acquire_start_lock(lock_path, stale_seconds=20) is None

    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: False)
    handle = client_module._acquire_start_lock(lock_path, stale_seconds=20)
    assert handle is not None
    handle.close()


@pytest.mark.parametrize("cancelled", [False, True])
def test_http_response_wait_is_bounded_and_cancellable(tmp_path, monkeypatch, cancelled):
    client = _client(tmp_path)
    connection_closed = threading.Event()
    cancellation = threading.Event() if cancelled else None

    class Response:
        will_close = False

        def read(self):
            assert connection_closed.wait(timeout=1)
            raise OSError("connection closed by client watchdog")

    class Connection:
        sock = object()
        send = lambda _self, _data: None

        def request(self, _method, _path, body=None, headers=None):
            self.send(body or b"request")

        def getresponse(self):
            return Response()

        def close(self):
            connection_closed.set()

    monkeypatch.setattr(client, "_connection", lambda _timeout: Connection())
    if cancelled:
        threading.Timer(0.02, cancellation.set).start()

    with pytest.raises(client_module._TransportFailure) as failure:
        client._pooled_open(
            "POST",
            "/api/search",
            b"{}",
            {},
            0.05 if not cancelled else 1.0,
            cancel_event=cancellation,
        )

    assert failure.value.cancelled is cancelled
    assert failure.value.request_not_sent is False


def test_cancelled_request_before_dispatch_is_marked_not_sent(tmp_path, monkeypatch):
    client = _client(tmp_path)
    cancellation = threading.Event()
    cancellation.set()
    calls = []
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: calls.append(True))

    result = client.post("/api/search", {"query": "needle"}, cancel_event=cancellation)

    assert result["cancelled"] is True
    assert result["request_not_sent"] is True
    assert result["outcome_unknown"] is False
    assert calls == []


def test_concurrent_cold_requests_share_one_service_start_and_readiness(tmp_path, monkeypatch):
    worker_count = 30
    client_root = tmp_path / "clients"
    client_root.mkdir()
    clients = [
        _client(client_root, tenant="", auto_start=True)
        for _ in range(worker_count)
    ]
    start_gate = threading.Barrier(worker_count)
    service_started = threading.Event()
    service_calls = []
    service_lock = threading.Lock()
    per_thread_probes: dict[int, int] = {}
    ready_probes: dict[int, int] = {}
    service_owner: list[int] = []
    probes_lock = threading.Lock()

    def online(self, _timeout=None):
        thread_id = threading.get_ident()
        with probes_lock:
            count = per_thread_probes.get(thread_id, 0) + 1
            per_thread_probes[thread_id] = count
            if service_started.is_set():
                ready_probes[thread_id] = ready_probes.get(thread_id, 0) + 1
        if count == 1:
            start_gate.wait(timeout=5)
            return False
        return service_started.is_set()

    def service_run(command, **kwargs):
        with service_lock:
            service_calls.append((command, kwargs))
            service_owner.append(threading.get_ident())
        service_started.set()
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(HubClient, "_online", online)
    monkeypatch.setattr(client_module.subprocess, "run", service_run)
    monkeypatch.setattr(client_module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(client_module, "process_identity", lambda pid: {
        "pid": pid,
        "creation_identity_type": "test_start_id",
        "creation_identity": 1,
    })
    monkeypatch.setattr(client_module, "pid_alive", lambda _pid: True)
    for client in clients:
        client.startup_wait = 2.0
        client.startup_poll = 0.01
        monkeypatch.setattr(
            client,
            "_pooled_open",
            lambda *_args, **_kwargs: (
                b'{"success":true}' if service_started.is_set() else (_ for _ in ()).throw(ConnectionRefusedError())
            ),
        )

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(client.post, "/api/search", {"query": f"query-{index}"}) for index, client in enumerate(clients)]
        results = [future.result(timeout=8) for future in futures]

    assert all(result == {"success": True} for result in results)
    assert len(service_calls) == 1
    command, options = service_calls[0]
    assert command[-1] == "start"
    assert Path(command[-2]) == Path(__file__).resolve().parents[1] / "tools" / "service.py"
    assert options["timeout"] <= 2.0
    assert options["env"]["LOCAL_AI_CONFIG"] == clients[0].config["_config_path"]
    assert all(probes >= 2 for probes in per_thread_probes.values())
    assert ready_probes[service_owner[0]] == 1


def test_concurrent_task_requests_derive_tenant_per_root_for_same_task_id(tmp_path, monkeypatch):
    client = _client(tmp_path)
    root_a = tmp_path / "worktree-a"
    root_b = tmp_path / "worktree-b"
    root_a.mkdir()
    root_b.mkdir()
    barrier = threading.Barrier(2)
    observed = []
    observed_lock = threading.Lock()

    def pooled_open(_method, path, body, headers, _timeout):
        barrier.wait(timeout=5)
        with observed_lock:
            observed.append((path, json.loads(body.decode("utf-8")), dict(headers)))
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    requests = (
        (
            {"root": str(root_a), "action": "get", "task_id": "same-task"},
            "same-request-id",
        ),
        (
            {"root": str(root_b), "action": "get", "task_id": "same-task"},
            "same-request-id",
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                client.post,
                "/api/agent-state/tasks",
                payload,
                request_id=request_id,
            )
            for payload, request_id in requests
        ]
        results = [future.result(timeout=6) for future in futures]

    assert results == [{"success": True}, {"success": True}]
    assert len(observed) == 2
    by_root = {payload["root"]: (path, payload, headers) for path, payload, headers in observed}
    assert set(by_root) == {str(root_a), str(root_b)}
    assert by_root[str(root_a)][0] == by_root[str(root_b)][0] == "/api/agent-state/tasks"
    assert by_root[str(root_a)][1] == requests[0][0]
    assert by_root[str(root_b)][1] == requests[1][0]
    assert by_root[str(root_a)][2]["X-LocalAI-Tenant"] == _expected_root_tenant(client, root_a)
    assert by_root[str(root_b)][2]["X-LocalAI-Tenant"] == _expected_root_tenant(client, root_b)
    assert by_root[str(root_a)][2]["X-LocalAI-Tenant"] != by_root[str(root_b)][2]["X-LocalAI-Tenant"]
    assert by_root[str(root_a)][2]["X-LocalAI-Request-ID"] == "same-request-id"
    assert by_root[str(root_b)][2]["X-LocalAI-Request-ID"] == "same-request-id"
    assert client.tenant == "tenant-default"


def test_root_scoped_post_accepts_only_matching_tenant_hints(tmp_path, monkeypatch):
    client = _client(tmp_path)
    root = tmp_path / "worktree"
    root.mkdir()
    observed = []

    def pooled_open(_method, path, body, headers, _timeout):
        observed.append((path, json.loads(body.decode("utf-8")), dict(headers)))
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    expected = _expected_root_tenant(client, root)
    payload = {"root": str(root), "action": "get", "task_id": "same-task", "tenant": expected}
    accepted = client.post(
        "/api/agent-state/tasks",
        payload,
        request_id="matching-hint",
        tenant=expected,
    )
    mismatched_header = client.post(
        "/api/agent-state/tasks",
        {"root": str(root), "action": "get", "task_id": "same-task"},
        request_id="mismatched-header",
        tenant="root-not-derived-here",
    )
    mismatched_body = client.post(
        "/api/agent-state/tasks",
        {"root": str(root), "action": "get", "task_id": "same-task", "tenant": "root-not-derived-here"},
        request_id="mismatched-body",
    )

    assert accepted == {"success": True}
    assert observed[0][0] == "/api/agent-state/tasks"
    assert observed[0][1] == payload
    assert observed[0][2]["X-LocalAI-Tenant"] == expected
    assert mismatched_header["error_code"] == "tenant_binding_mismatch"
    assert mismatched_body["error_code"] == "tenant_binding_mismatch"
    assert mismatched_header["terminal"] is mismatched_body["terminal"] is True
    assert mismatched_header["retryable"] is mismatched_body["retryable"] is False
    assert len(observed) == 1
    assert client.tenant == "tenant-default"


def test_post_without_tenant_override_keeps_client_default(tmp_path, monkeypatch):
    client = _client(tmp_path)
    observed = []

    def pooled_open(_method, path, body, headers, _timeout):
        observed.append((path, json.loads(body.decode("utf-8")), dict(headers)))
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", pooled_open)
    payload = {"root": "C:/worktrees/default", "task": "task-default", "query": "needle"}

    result = client.post("/api/search", payload, request_id="request-default")

    assert result == {"success": True}
    assert len(observed) == 1
    assert observed[0][0] == "/api/search"
    assert observed[0][1] == payload
    assert observed[0][2]["X-LocalAI-Tenant"] == "tenant-default"
    assert observed[0][2]["X-LocalAI-Request-ID"] == "request-default"
    rejected = client.post(
        "/api/search",
        payload,
        request_id="request-other-tenant",
        tenant="arbitrary-tenant",
    )
    assert rejected["error_code"] == "tenant_binding_mismatch"
    assert rejected["terminal"] is True
    assert rejected["retryable"] is False
    assert len(observed) == 1
    assert client.tenant == "tenant-default"


def test_empty_client_tenant_omits_tenant_header(tmp_path, monkeypatch):
    client = _client(tmp_path, tenant="")
    observed = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda _method, _path, _body, headers, _timeout: observed.append(dict(headers)) or b'{"success":true}',
    )

    result = client.post("/api/search", {"query": "needle"})

    assert result == {"success": True}
    assert len(observed) == 1
    assert "X-LocalAI-Tenant" not in observed[0]
    assert not any(value.startswith("agent-") for value in observed[0].values())


def test_root_scoped_tenant_uses_fallback_key_and_fixed_api_token_tenant(tmp_path, monkeypatch):
    client = _client(
        tmp_path,
        security_overrides={
            "api_token_tenant": "fixed-api-token-tenant",
            "api_token_principal": "lower-priority-principal",
            "tenant_derivation_key": None,
        },
    )
    root = tmp_path / "worktree"
    root.mkdir()
    observed = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda _method, path, body, headers, _timeout: observed.append(
            (path, json.loads(body.decode("utf-8")), dict(headers))
        ) or b'{"success":true}',
    )

    result = client.post(
        "/api/agent-state/tasks",
        {"root": str(root), "action": "get", "task_id": "task-a"},
    )

    assert result == {"success": True}
    assert observed[0][2]["X-LocalAI-Tenant"] == _expected_root_tenant(client, root)
    assert observed[0][2]["X-LocalAI-Tenant"] != client.tenant


def test_rootless_memory_uses_principal_and_rejects_mismatched_hint(tmp_path, monkeypatch):
    client = _client(tmp_path)
    observed = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda _method, path, body, headers, _timeout: observed.append(
            (path, json.loads(body.decode("utf-8")), dict(headers))
        ) or b'{"success":true}',
    )

    accepted = client.post(
        "/api/agent-state/memory",
        {"action": "find", "scope": "global"},
    )
    rejected = client.post(
        "/api/agent-state/memory",
        {"action": "find", "scope": "session"},
        tenant="other-principal",
    )

    assert accepted == {"success": True}
    assert observed[0][2]["X-LocalAI-Tenant"] == "fixed-principal"
    assert rejected["error_code"] == "tenant_binding_mismatch"
    assert rejected["terminal"] is True
    assert rejected["retryable"] is False
    assert len(observed) == 1
    assert client.tenant == "tenant-default"


def test_tokenless_agent_state_uses_server_principal_not_client_tenant(tmp_path):
    client = _client(
        tmp_path,
        tenant="client-selected-tenant",
        security_overrides={
            "api_token": "",
            "api_token_tenant": "",
            "api_token_principal": "",
            "tenant_derivation_key": "",
            "allowed_roots": [],
        },
    )

    tenant, error = client._request_tenant(
        "/api/agent-state/memory",
        {"action": "find", "scope": "global"},
        None,
    )
    mismatch, mismatch_error = client._request_tenant(
        "/api/agent-state/memory",
        {"action": "find", "scope": "global", "tenant": "client-selected-tenant"},
        None,
    )

    assert (tenant, error) == ("api-token-default", None)
    assert mismatch is None
    assert mismatch_error["error_code"] == "tenant_binding_mismatch"


def test_configured_token_with_empty_allowlist_rejects_root_scoped_request(tmp_path):
    client = _client(
        tmp_path,
        security_overrides={"allowed_roots": [], "tenant_derivation_key": ""},
    )

    tenant, error = client._request_tenant(
        "/api/agent-state/tasks",
        {"root": str(tmp_path), "task_id": "task-empty-allowlist"},
        None,
    )

    assert tenant is None
    assert error["error_code"] == "root_not_allowed"


def test_explicit_root_allowlist_rejects_outside_agent_state_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    client = _client(tmp_path, allowed_roots=[allowed])

    tenant, error = client._request_tenant(
        "/api/agent-state/tasks",
        {"root": str(outside), "task_id": "task-outside-allowlist"},
        None,
    )

    assert tenant is None
    assert error["error_code"] == "root_not_allowed"


@pytest.mark.parametrize(
    ("security_overrides", "expected_principal"),
    [
        ({"api_token_tenant": None, "api_token_principal": "principal-fallback"}, "principal-fallback"),
        ({"api_token_tenant": None, "api_token_principal": None}, "api-token-default"),
    ],
)
def test_rootless_memory_uses_configured_principal_fallbacks(
    tmp_path, monkeypatch, security_overrides, expected_principal
):
    client = _client(tmp_path, security_overrides=security_overrides)
    observed = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda _method, path, body, headers, _timeout: observed.append(
            (path, dict(headers))
        ) or b'{"success":true}',
    )

    result = client.post("/api/agent-state/memory", {"action": "find", "scope": "session"})

    assert result == {"success": True}
    assert observed[0][1]["X-LocalAI-Tenant"] == expected_principal
    assert observed[0][1]["X-LocalAI-Tenant"] != client.tenant


def test_get_derives_root_tenant_from_query_and_rejects_mismatch(tmp_path, monkeypatch):
    client = _client(tmp_path)
    root = tmp_path / "worktree"
    root.mkdir()
    query = urlencode({"root": str(root), "scope": "repository", "task_id": "same-task"})
    path = f"/api/agent-state/memory?{query}"
    observed = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda _method, request_path, _body, headers, _timeout: observed.append(
            (request_path, dict(headers))
        ) or b'{"success":true}',
    )
    expected = _expected_root_tenant(client, root)

    accepted = client.get(path, tenant=expected)
    rejected = client.get(path, tenant="wrong-root-tenant")

    assert accepted == {"success": True}
    assert observed[0][0] == path
    assert observed[0][1]["X-LocalAI-Tenant"] == expected
    assert rejected["error_code"] == "tenant_binding_mismatch"
    assert rejected["terminal"] is True
    assert rejected["retryable"] is False
    assert len(observed) == 1


def test_get_task_derives_root_tenant_from_query(tmp_path, monkeypatch):
    client = _client(tmp_path)
    root = tmp_path / "worktree"
    root.mkdir()
    path = f"/api/agent-state/tasks?{urlencode({'root': str(root), 'task_id': 'same-task'})}"
    observed = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda _method, request_path, _body, headers, _timeout: observed.append(
            (request_path, dict(headers))
        ) or b'{"success":true}',
    )

    result = client.get(path)

    assert result == {"success": True}
    assert observed[0][0] == path
    assert observed[0][1]["X-LocalAI-Tenant"] == _expected_root_tenant(client, root)


def test_memory_payload_derives_tenant_from_nested_root(tmp_path, monkeypatch):
    client = _client(tmp_path)
    root = tmp_path / "worktree"
    root.mkdir()
    expected = _expected_root_tenant(client, root)
    observed = []
    payload = {
        "action": "record",
        "scope": "repository",
        "record": {"root": str(root), "tenant": expected, "scope": "repository"},
        "provenance": {"root": str(root), "tenant": expected},
    }
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda _method, path, body, headers, _timeout: observed.append(
            (path, json.loads(body.decode("utf-8")), dict(headers))
        ) or b'{"success":true}',
    )

    result = client.post("/api/agent-state/memory", payload)

    assert result == {"success": True}
    assert observed[0][1] == payload
    assert observed[0][2]["X-LocalAI-Tenant"] == expected


@pytest.mark.parametrize("root_case", ["missing", "outside", "symlink"])
def test_root_scoped_task_rejects_invalid_roots_before_http(tmp_path, monkeypatch, root_case):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    if root_case == "missing":
        root = allowed / "missing"
    elif root_case == "outside":
        root = tmp_path / "outside"
        root.mkdir()
    else:
        target = allowed / "target"
        target.mkdir()
        root = allowed / "linked"
        try:
            root.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory symlinks unavailable: {exc}")
    client = _client(tmp_path, allowed_roots=[allowed])
    attempts = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda *_args, **_kwargs: attempts.append(True) or b'{"success":true}',
    )

    result = client.post(
        "/api/agent-state/tasks",
        {"root": str(root), "action": "get", "task_id": "task-a"},
    )

    assert result["error_code"] == "root_not_allowed"
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["preflight"] is True
    assert attempts == []


def test_scoped_task_and_memory_requests_require_root_before_http(tmp_path, monkeypatch):
    client = _client(tmp_path)
    attempts = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda *_args, **_kwargs: attempts.append(True) or b'{"success":true}',
    )

    task_post = client.post("/api/agent-state/tasks", {"action": "get", "task_id": "task-a"})
    task_get = client.get("/api/agent-state/tasks?task_id=task-a")
    memory_task = client.post(
        "/api/agent-state/memory",
        {"action": "find", "scope": "task", "task_id": "task-a"},
    )

    assert task_post["error_code"] == "root_not_allowed"
    assert task_get["error_code"] == "root_not_allowed"
    assert memory_task["error_code"] == "root_required"
    assert all(result["terminal"] is True and result["retryable"] is False for result in (task_post, task_get, memory_task))
    assert attempts == []


@pytest.mark.parametrize(
    "tenant",
    [
        "",
        "tenant with space",
        "tenant\r\nX: injected",
        "tenant\x00control",
        "x" * 129,
        "tenant\u007f",
        "tenant-é",
    ],
)
def test_invalid_tenant_override_is_terminal_preflight_without_http(tmp_path, monkeypatch, tenant):
    client = _client(tmp_path)
    attempts = []
    monkeypatch.setattr(
        client,
        "_pooled_open",
        lambda *_args, **_kwargs: attempts.append(True) or b'{"success":true}',
    )

    result = client.post(
        "/api/search",
        {"root": "C:/worktrees/a", "task": "task-a", "query": "needle"},
        request_id="valid-request-id",
        tenant=tenant,
    )

    assert result == {
        "success": False,
        "error": "tenant must be 1-128 visible ASCII characters without whitespace",
        "error_code": "tenant_binding_mismatch",
        "terminal": True,
        "retryable": False,
        "preflight": True,
    }
    assert attempts == []
    assert client.tenant == "tenant-default"
