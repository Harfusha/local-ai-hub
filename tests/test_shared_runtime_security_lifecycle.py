from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server, process_utils


def _handler(headers: dict[str, str], *, method: str = "GET", path: str = "/api/status"):
    handler = object.__new__(http_server.Handler)
    handler.headers = headers
    handler.command = method
    handler.path = path
    return handler


def _dispatch_get(
    monkeypatch,
    path: str,
    app,
    *,
    headers: dict[str, str] | None = None,
    authenticate: bool = False,
):
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler(headers or {}, path=path)
    responses = []
    handler._begin_trace = lambda *_args: None
    if authenticate:
        handler.server = SimpleNamespace(check_rate_limit=lambda _tenant: True)
        handler._require_authorized = lambda *args, **kwargs: http_server.Handler._require_authorized(
            handler, *args, **kwargs
        )
    else:
        handler._require_authorized = lambda *_args, **_kwargs: True
    handler._send = lambda status, payload: responses.append((status, payload))
    handler._finish_debug_trace = lambda *_args, **_kwargs: None
    handler._close_trace_context = lambda: None
    http_server.Handler.do_GET(handler)
    return responses


def _dispatch_post(
    monkeypatch,
    path: str,
    payload: dict,
    app,
    *,
    headers: dict[str, str] | None = None,
    authenticate: bool = False,
):
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler(headers or {}, method="POST", path=path)
    responses = []
    handler._begin_trace = lambda *_args: None
    handler._validate_host_and_origin = lambda: True
    if authenticate:
        handler.server = SimpleNamespace(check_rate_limit=lambda _tenant: True)
        handler._require_authorized = lambda *args, **kwargs: http_server.Handler._require_authorized(
            handler, *args, **kwargs
        )
    else:
        handler._require_authorized = lambda *_args, **_kwargs: True
    handler._read_json = lambda: payload
    handler._validate_payload = lambda *_args: None
    handler._send = lambda status, data: responses.append((status, data))
    http_server.Handler.do_POST(handler)
    return responses


def _store_spy(calls):
    class StoreSpy:
        def __getattr__(self, name):
            def record(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"success": True}
            return record
    return StoreSpy()


def test_api_token_acl_preserves_tenant_scope(monkeypatch):
    app = SimpleNamespace(config={
        "security": {
            "api_token": "alice-user-credential-long",
            "api_token_permissions": ["read", "write"],
            "api_token_tenant": "tenant-alice",
        }
    })
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler({
        "X-LocalAI-Token": "alice-user-credential-long",
        "X-LocalAI-Tenant": "tenant-alice",
    }, method="POST", path="/api/delegate")

    assert http_server.Handler._authorized(handler, "write") is True
    assert handler._authorization_actor == "tenant-alice"
    assert http_server.Handler._tenant(handler) == "tenant-alice"


def test_http_user_acl_denies_admin_and_invalid_credential(monkeypatch):
    app = SimpleNamespace(config={
        "security": {
            "api_token": "alice-user-credential-long",
            "api_token_permissions": ["read"],
        }
    })
    monkeypatch.setattr(http_server, "APP", app)
    valid = _handler({
        "X-LocalAI-Token": "alice-user-credential-long",
        "X-LocalAI-Tenant": "tenant-alice",
    }, method="POST", path="/api/admin/mode")
    invalid = _handler({
        "X-LocalAI-Token": "wrong-credential",
        "X-LocalAI-Tenant": "tenant-alice",
    })

    assert http_server.Handler._authorized(valid, "admin") is False
    assert valid._authorization_status == 403
    assert http_server.Handler._authorized(invalid, "read") is False
    assert invalid._authorization_status == 401


def test_api_token_tenant_binding_rejects_tenant_switch(monkeypatch):
    app = SimpleNamespace(config={
        "security": {
            "api_token": "tenant-bound-token-long",
            "api_token_tenant": "tenant-alice",
        }
    })
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler({
        "X-LocalAI-Token": "tenant-bound-token-long",
        "X-LocalAI-Tenant": "tenant-other",
    })
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert http_server.Handler._authorized(handler, "read") is True
    assert http_server.Handler._tenant_binding_allowed(handler) is False
    assert responses[0][0] == 403


def test_unbound_client_tenant_header_cannot_choose_principal(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {"api_token": "unbound-token-long"}
    }))
    handler = _handler({
        "X-LocalAI-Token": "unbound-token-long",
        "X-LocalAI-Tenant": "tenant-spoof",
    })
    assert http_server.Handler._authorized(handler, "read") is True
    assert http_server.Handler._tenant(handler) == "api-token-default"


def test_rootless_memory_binding_rejects_untrusted_tenant_header(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {"api_token": "unbound-token-long"}
    }))
    handler = _handler({
        "X-LocalAI-Token": "unbound-token-long",
        "X-LocalAI-Tenant": "tenant-spoof",
    })
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert http_server.Handler._authorized(handler, "read") is True
    assert http_server.Handler._bind_principal_tenant(handler) is False
    assert responses[0][0] == 403

    trusted = _handler({"X-LocalAI-Token": "unbound-token-long"})
    assert http_server.Handler._authorized(trusted, "read") is True
    assert http_server.Handler._bind_principal_tenant(trusted) is True
    assert trusted._authorization_tenant == "api-token-default"


def test_missing_credentials_fail_closed_and_legacy_global_token_remains(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {}}))
    anonymous = _handler({})
    assert http_server.Handler._authorized(anonymous, "admin") is False
    assert anonymous._authorization_status == 401

    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {"api_token": "legacy-secret"}}),
    )
    assert http_server.Handler._authorized(
        _handler({"Authorization": "Bearer legacy-secret"}), "admin"
    ) is True


def test_config_loads_per_user_api_token_acl_and_tenant_binding(tmp_path):
    from local_ai_hub.config import load_config

    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[security]\napi_token = "per-user-token-credential"\n'
        'api_token_tenant = "tenant-alice"\n'
        'tenant_derivation_key = "stable-test-derivation-secret-0123456789"\n'
        f'allowed_roots = ["{tmp_path.as_posix()}"]\n'
        'api_token_permissions = ["monitor", "read"]\n'
        '[hardware]\nprofile = "cpu"\nauto_tune = true\n',
        encoding="utf-8",
    )

    loaded = load_config(str(config))

    assert loaded["security"]["api_token_tenant"] == "tenant-alice"
    assert loaded["security"]["allowed_roots"] == [str(tmp_path.as_posix())]
    assert loaded["security"]["api_token_permissions"] == ["monitor", "read"]


@pytest.fixture
def readiness_server(monkeypatch):
    monkeypatch.setattr(http_server, "APP", None)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get_json(url: str, *, token: str = "") -> tuple[int, dict]:
    headers = {"X-LocalAI-Token": token} if token else {}
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=1.0) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_liveness_stays_healthy_while_readiness_waits_for_app(readiness_server):
    health_status, health = _get_json(f"{readiness_server}/health")
    ready_status, ready = _get_json(f"{readiness_server}/ready")

    assert health_status == 200
    assert health["hub_online"] is True
    assert ready_status == 503
    assert ready["ready"] is False
    assert ready["retryable"] is True


def test_readiness_is_ready_only_for_initialized_open_app(readiness_server, monkeypatch):
    token = "readiness-probe-token-long"
    config = {"security": {"api_token": token}}
    stores = {name: object() for name in http_server.READINESS_COMPONENTS}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(_closed=True, config=config, **stores))
    closed_status, closed = _get_json(f"{readiness_server}/ready", token=token)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(_closed=False, config=config, **stores))
    ready_status, ready = _get_json(f"{readiness_server}/ready", token=token)

    assert closed_status == 503
    assert closed["ready"] is False
    assert ready_status == 200
    assert ready["ready"] is True


def test_readiness_requires_initialized_core_stores(readiness_server, monkeypatch):
    token = "readiness-probe-token-long"
    stores = {name: object() for name in http_server.READINESS_COMPONENTS}
    stores["telemetry"] = None
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            _closed=False,
            config={"security": {"api_token": token}},
            **stores,
        ),
    )

    status, result = _get_json(f"{readiness_server}/ready", token=token)

    assert status == 503
    assert result["ready"] is False
    assert result["reason"] == "required_store_unavailable"


def test_readiness_requires_monitor_auth_after_app_initializes(readiness_server, monkeypatch):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            _closed=False,
            config={"security": {"api_token": "readiness-probe-token-long"}},
            artifacts=object(),
            telemetry=object(),
            agent_state=object(),
        ),
    )

    status, result = _get_json(f"{readiness_server}/ready")

    assert status == 401
    assert result["error"] == "unauthorized"


def test_readiness_is_loopback_only():
    handler = _handler({})
    handler.client_address = ("198.51.100.22", 42310)

    assert http_server.Handler._loopback_client(handler) is False


def test_hub_listener_rejects_second_process_on_same_endpoint():
    first = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    host, port = first.server_address
    try:
        with pytest.raises(OSError):
            http_server.LocalAIHTTPServer((host, port), http_server.Handler)
    finally:
        first.server_close()


def test_supervisor_readiness_requires_owned_child_ready_response(tmp_path, monkeypatch):
    module, supervisor, state_dir = _supervisor_for_lifecycle(tmp_path, monkeypatch)
    child = SimpleNamespace(pid=4242, poll=lambda: None)
    owner = _owner_record(child.pid, state_dir, "hub")
    supervisor.child = child
    supervisor.child_owner = owner
    monkeypatch.setattr(module, "process_owner_state", lambda *_args: "owned")
    monkeypatch.setattr(module, "find_listening_pid", lambda _port: child.pid)

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    probes = []
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: probes.append((request.full_url, timeout)) or Response(b'{"ready":true}'))

    assert supervisor.hub_online() is False
    assert supervisor.hub_ready() is True
    assert probes == [("http://127.0.0.1:11435/ready", 1.0)]
    supervisor.child_ready = True
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: Response(b"{}"))
    assert supervisor.hub_online() is True

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: Response(b'{"ready":false}'))
    assert supervisor.hub_ready() is False
    monkeypatch.setattr(module, "find_listening_pid", lambda _port: child.pid + 1)
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: Response(b'{"ready":true}'))
    assert supervisor.hub_ready() is False


def test_process_owner_identity_binds_pid_creation_executable_state_and_role(tmp_path, monkeypatch):
    identity = {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
    }
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: dict(identity))
    record = process_utils.process_owner_record(4242, tmp_path / "state", "hub")

    assert record["pid"] == 4242
    assert record["role"] == "hub"
    assert record["state_dir"] == str((tmp_path / "state").resolve())
    assert process_utils.process_owner_state(record, tmp_path / "state", "hub") == "owned"
    assert process_utils.process_owner_state(record, tmp_path / "other", "hub") == "unknown"
    assert process_utils.process_owner_state(record, tmp_path / "state", "supervisor") == "unknown"


def test_process_owner_state_detects_pid_reuse_and_fails_closed_on_unknown_identity(tmp_path, monkeypatch):
    record = {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
        "state_dir": str((tmp_path / "state").resolve()),
        "role": "hub",
    }
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 78,
        "creation_identity_type": "test_start_time",
    })
    assert process_utils.process_owner_state(record, tmp_path / "state", "hub") == "stale"

    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: None)
    monkeypatch.setattr(process_utils, "pid_alive", lambda _pid: True)
    assert process_utils.process_owner_state(record, tmp_path / "state", "hub") == "unknown"


def test_supervisor_lock_records_and_releases_exact_process_owner(tmp_path, monkeypatch):
    from local_ai_hub import supervisor as supervisor_module

    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\nport = 11435\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor_module, "OllamaRuntime", lambda _config: object())
    monkeypatch.setattr(process_utils, "process_identity", lambda pid: {
        "pid": pid,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
    })
    supervisor = supervisor_module.Supervisor(str(config))

    assert supervisor.acquire() is True
    owner = json.loads(supervisor.lock_path.read_text(encoding="utf-8"))
    assert owner["pid"] == supervisor_module.os.getpid()
    assert owner["role"] == "supervisor"
    supervisor.release_lock()
    assert supervisor.lock_path.exists() is False


def test_supervisor_shutdown_does_not_kill_reused_child_pid(tmp_path, monkeypatch):
    from local_ai_hub import supervisor as supervisor_module

    state_dir = tmp_path / "state"
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\nport = 11435\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor_module, "OllamaRuntime", lambda _config: object())
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 78,
        "creation_identity_type": "test_start_time",
    })
    monkeypatch.setattr(supervisor_module, "find_listening_pid", lambda _port: None)
    supervisor = supervisor_module.Supervisor(str(config))
    supervisor.child_owner = {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
        "state_dir": str(state_dir.resolve()),
        "role": "hub",
    }
    child_killed = []
    def wait(*, timeout):
        raise subprocess.TimeoutExpired("child", timeout)
    supervisor.child = SimpleNamespace(
        pid=4242,
        poll=lambda: None,
        wait=wait,
        kill=lambda: child_killed.append(True),
    )
    monkeypatch.setattr(supervisor_module, "terminate_process_handle", lambda *_args, **_kwargs: False)

    supervisor.terminate_child()

    assert child_killed == []
    assert (state_dir / "hub.pid").exists() is False


def test_service_shutdown_never_kills_pid_reused_by_another_process(tmp_path, monkeypatch):
    from local_ai_hub import config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *_args: {
        "server": {"state_dir": str(tmp_path), "port": 11435},
        "headless": {},
        "_config_path": str(tmp_path / "config.toml"),
    })
    service_path = Path(__file__).parents[1] / "tools" / "service.py"
    spec = importlib.util.spec_from_file_location("test_service_identity_stop", service_path)
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    owner = {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
        "state_dir": str(tmp_path.resolve()),
        "role": "hub",
    }
    (tmp_path / "hub.pid").write_text("4242", encoding="utf-8")
    (tmp_path / "hub.owner.json").write_text(json.dumps(owner), encoding="utf-8")
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 78,
        "creation_identity_type": "test_start_time",
    })
    killed = []
    monkeypatch.setattr(service, "terminate_owned_process", lambda *args, **_kwargs: killed.append(args[0]["pid"]))
    monkeypatch.setattr(service, "find_listening_pid", lambda _port: 4242)

    service.kill_hub()

    assert killed == []


def test_service_shutdown_terminates_only_matching_owner(tmp_path, monkeypatch):
    from local_ai_hub import config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *_args: {
        "server": {"state_dir": str(tmp_path), "port": 11435},
        "headless": {},
        "_config_path": str(tmp_path / "config.toml"),
    })
    service_path = Path(__file__).parents[1] / "tools" / "service.py"
    spec = importlib.util.spec_from_file_location("test_service_identity_owned_stop", service_path)
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    owner = {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
        "state_dir": str(tmp_path.resolve()),
        "role": "hub",
    }
    (tmp_path / "hub.pid").write_text("4242", encoding="utf-8")
    (tmp_path / "hub.owner.json").write_text(json.dumps(owner), encoding="utf-8")
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
    })
    killed = []
    monkeypatch.setattr(service, "terminate_owned_process", lambda *args, **_kwargs: killed.append(args[0]["pid"]))
    monkeypatch.setattr(service, "find_listening_pid", lambda _port: 4242)

    service.kill_hub()

    assert killed == [4242]


def _supervisor_for_lifecycle(tmp_path, monkeypatch, *, headless=""):
    from local_ai_hub import supervisor as supervisor_module

    state_dir = tmp_path / "state"
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\nport = 11435\nbind = "127.0.0.1"\n{headless}',
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor_module, "OllamaRuntime", lambda _config: object())
    supervisor = supervisor_module.Supervisor(str(config))
    real_os = supervisor_module.os
    monkeypatch.setattr(supervisor_module, "os", SimpleNamespace(
        name=real_os.name,
        environ=real_os.environ,
        pathsep=real_os.pathsep,
        getpid=real_os.getpid,
        open=real_os.open,
        fstat=real_os.fstat,
        lseek=real_os.lseek,
        fsync=real_os.fsync,
        write=real_os.write,
        close=real_os.close,
        replace=real_os.replace,
        O_CREAT=real_os.O_CREAT,
        O_EXCL=real_os.O_EXCL,
        O_WRONLY=real_os.O_WRONLY,
        O_RDWR=real_os.O_RDWR,
        O_BINARY=getattr(real_os, "O_BINARY", 0),
        SEEK_SET=real_os.SEEK_SET,
    ))
    return supervisor_module, supervisor, state_dir


def _owner_record(pid: int, state_dir, role: str = "supervisor", *, creation=None):
    return {
        "pid": pid,
        "executable": "/usr/bin/python3",
        "creation_identity": pid if creation is None else creation,
        "creation_identity_type": "test_start_time",
        "state_dir": str(Path(state_dir).resolve()),
        "role": role,
    }


def test_supervisor_recovers_expired_lock_and_preserves_current_owner(tmp_path, monkeypatch):
    module, supervisor, state_dir = _supervisor_for_lifecycle(tmp_path, monkeypatch)
    expired = _owner_record(4242, state_dir, creation=77)
    supervisor.lock_path.write_text(json.dumps(expired), encoding="utf-8")
    monkeypatch.setattr(module, "process_owner_record", lambda pid, path, role: _owner_record(pid, path, role))
    monkeypatch.setattr(
        module,
        "process_owner_state",
        lambda owner, _path, _role: "stale" if owner["pid"] == 4242 else "owned",
    )

    assert supervisor.acquire() is True
    replacement = json.loads(supervisor.lock_path.read_text(encoding="utf-8"))
    assert replacement["pid"] == module.os.getpid()
    supervisor.release_lock()


def test_supervisor_lock_does_not_reclaim_foreign_or_unknown_owner(tmp_path, monkeypatch):
    module, supervisor, state_dir = _supervisor_for_lifecycle(tmp_path, monkeypatch)
    foreign = _owner_record(4242, state_dir, creation=77)
    supervisor.lock_path.write_text(json.dumps(foreign), encoding="utf-8")
    monkeypatch.setattr(module, "process_owner_record", lambda pid, path, role: _owner_record(pid, path, role))
    monkeypatch.setattr(process_utils, "process_identity", lambda pid: {
        "pid": pid,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
    })
    monkeypatch.setattr(module, "process_owner_state", process_utils.process_owner_state)
    assert process_utils.process_owner_state(foreign, state_dir, "supervisor") == "owned"

    assert supervisor.acquire() is False
    assert json.loads(supervisor.lock_path.read_text(encoding="utf-8")) == foreign

    foreign["state_dir"] = str((tmp_path / "other-state").resolve())
    supervisor.lock_path.write_text(json.dumps(foreign), encoding="utf-8")
    assert process_utils.process_owner_state(foreign, state_dir, "supervisor") == "unknown"
    assert supervisor.acquire() is False
    assert json.loads(supervisor.lock_path.read_text(encoding="utf-8")) == foreign

    foreign["state_dir"] = str(state_dir.resolve())
    foreign["executable"] = "/usr/bin/foreign-python"
    supervisor.lock_path.write_text(json.dumps(foreign), encoding="utf-8")
    assert process_utils.process_owner_state(foreign, state_dir, "supervisor") == "unknown"
    assert supervisor.acquire() is False
    assert json.loads(supervisor.lock_path.read_text(encoding="utf-8")) == foreign


def test_concurrent_stale_lock_reclaim_has_exactly_one_supervisor(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\nport = 11435\n',
        encoding="utf-8",
    )
    stale = _owner_record(2**31 - 2, state_dir)
    (state_dir / "supervisor.lock").write_text(json.dumps(stale), encoding="utf-8")
    gate = tmp_path / "go"
    release = tmp_path / "release"
    script = """
import sys, time
from pathlib import Path
from local_ai_hub.supervisor import Supervisor
config, ready, gate, attempted, release = map(Path, sys.argv[1:])
supervisor = Supervisor(str(config))
ready.write_text('ready')
deadline = time.monotonic() + 10
while not gate.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
won = supervisor.acquire()
attempted.write_text('WON' if won else 'LOST')
print('WON' if won else 'LOST', flush=True)
if won:
    try:
        deadline = time.monotonic() + 10
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        supervisor.release_lock()
"""
    env = os.environ.copy()
    source = str(Path(__file__).parents[1] / "src")
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(config), str(tmp_path / f"ready-{index}"),
             str(gate), str(tmp_path / f"attempted-{index}"), str(release)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            **process_utils.hidden_run_kwargs(text=True),
        )
        for index in range(2)
    ]
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not all((tmp_path / f"ready-{index}").exists() for index in range(2)):
            time.sleep(0.01)
        assert all((tmp_path / f"ready-{index}").exists() for index in range(2))
        gate.write_text("go", encoding="utf-8")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not all((tmp_path / f"attempted-{index}").exists() for index in range(2)):
            time.sleep(0.01)
        # Keep the winner alive until both contenders actually attempted acquire.
        # A fixed sleep allowed sequential wins under Windows scheduling delays.
        assert all((tmp_path / f"attempted-{index}").exists() for index in range(2))
        assert sum((tmp_path / f"attempted-{index}").read_text() == "WON" for index in range(2)) == 1
    finally:
        release.write_text("release", encoding="utf-8")
        for worker in workers:
            if worker.poll() is None:
                try:
                    worker.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=3)
    results = [worker.communicate(timeout=3) for worker in workers]

    assert all(worker.returncode == 0 for worker in workers), results
    assert sum(stdout.strip() == "WON" for stdout, _stderr in results) == 1


def test_crashed_supervisor_releases_os_guard_and_next_process_reclaims_owner(tmp_path):
    state_dir = tmp_path / "state"
    config = tmp_path / "hub.toml"
    config.write_text(
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\nport = 11435\n',
        encoding="utf-8",
    )
    script = "import os, sys; from local_ai_hub.supervisor import Supervisor; s=Supervisor(sys.argv[1]); assert s.acquire(); print('LOCKED', flush=True); os._exit(0)"
    env = os.environ.copy()
    source = str(Path(__file__).parents[1] / "src")
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    crashed = subprocess.run(
        [sys.executable, "-B", "-c", script, str(config)],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
        check=False,
    )
    assert crashed.returncode == 0, crashed.stderr
    assert crashed.stdout.strip() == "LOCKED"

    from local_ai_hub.supervisor import Supervisor

    replacement = Supervisor(str(config))
    assert replacement.acquire() is True
    owner = json.loads(replacement.lock_path.read_text(encoding="utf-8"))
    assert owner["pid"] == os.getpid()
    replacement.release_lock()


def test_concurrent_cold_hub_binds_allow_only_one_pre_app_process(tmp_path):
    reservation = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    host, port = reservation.server_address
    reservation.server_close()
    gate = tmp_path / "start"
    script = "import sys, time; from pathlib import Path; from local_ai_hub.http_server import Handler, LocalAIHTTPServer; host, port, gate = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3]); deadline = time.monotonic() + 10\nwhile not gate.exists() and time.monotonic() < deadline: time.sleep(0.01)\ntry: server = LocalAIHTTPServer((host, port), Handler)\nexcept OSError: print('BLOCKED', flush=True)\nelse: print('BOUND', flush=True); time.sleep(0.5); server.server_close()"
    env = os.environ.copy()
    source = str(Path(__file__).parents[1] / "src")
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    workers = [
        subprocess.Popen(
            [sys.executable, "-B", "-c", script, host, str(port), str(gate)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(2)
    ]
    gate.write_text("go", encoding="utf-8")
    results = [worker.communicate(timeout=15) for worker in workers]

    assert all(worker.returncode == 0 for worker in workers), results
    assert sorted(stdout.strip() for stdout, _stderr in results) == ["BLOCKED", "BOUND"]


def test_supervisor_persists_child_owner_immediately_after_spawn(tmp_path, monkeypatch):
    module, supervisor, state_dir = _supervisor_for_lifecycle(tmp_path, monkeypatch)
    child = SimpleNamespace(pid=54321)
    owner = _owner_record(child.pid, state_dir, "hub")
    monkeypatch.setattr(supervisor, "spawn_hub", lambda: child)
    monkeypatch.setattr(module, "process_owner_record", lambda *_args: owner)
    monkeypatch.setattr(module, "open_pidfd", lambda _pid: None)

    assert supervisor._start_child() is child
    assert json.loads((state_dir / "hub.owner.json").read_text(encoding="utf-8")) == owner
    assert (state_dir / "hub.pid").read_text(encoding="utf-8") == str(child.pid)


def test_child_owner_persist_failure_uses_retained_child_handle_only(tmp_path, monkeypatch):
    module, supervisor, _state_dir = _supervisor_for_lifecycle(tmp_path, monkeypatch)
    child = SimpleNamespace(pid=54321)
    monkeypatch.setattr(supervisor, "spawn_hub", lambda: child)
    monkeypatch.setattr(module, "process_owner_record", lambda *_args: None)
    monkeypatch.setattr(module, "open_pidfd", lambda _pid: 678)
    stopped = []
    monkeypatch.setattr(module, "terminate_process_handle", lambda process, pidfd, **_kwargs: stopped.append((process, pidfd)) or True)

    with pytest.raises(RuntimeError, match="could not persist hub process owner"):
        supervisor._start_child()

    assert stopped == [(child, 678)]


def test_external_termination_fails_closed_on_darwin(monkeypatch, tmp_path):
    owner = _owner_record(4242, tmp_path, "hub", creation=77)
    original_os = process_utils.os
    monkeypatch.setattr(process_utils, "os", SimpleNamespace(
        name="posix", path=original_os.path,
        normcase=original_os.path.normcase, normpath=original_os.path.normpath,
    ))
    monkeypatch.setattr(process_utils, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(process_utils, "process_owner_state", lambda *_args: "owned")
    monkeypatch.setattr(process_utils, "open_pidfd", lambda _pid: None)
    signalled = []
    monkeypatch.setattr(process_utils.signal, "pidfd_send_signal", lambda *_args: signalled.append(True), raising=False)

    assert process_utils.terminate_owned_process(owner, tmp_path, "hub") is False
    assert signalled == []


def test_external_termination_does_not_signal_reused_pidfd(monkeypatch, tmp_path):
    owner = _owner_record(4242, tmp_path, "hub", creation=77)
    original_os = process_utils.os
    monkeypatch.setattr(process_utils, "os", SimpleNamespace(
        name="posix", path=original_os.path,
        normcase=original_os.path.normcase, normpath=original_os.path.normpath,
    ))
    monkeypatch.setattr(process_utils, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(process_utils, "process_owner_state", lambda *_args: "owned")
    monkeypatch.setattr(process_utils, "open_pidfd", lambda _pid: 678)
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 78,
        "creation_identity_type": "test_start_time",
    })
    monkeypatch.setattr(process_utils, "close_pidfd", lambda _pidfd: None)
    signalled = []
    monkeypatch.setattr(process_utils.signal, "pidfd_send_signal", lambda *_args: signalled.append(True), raising=False)

    assert process_utils.terminate_owned_process(owner, tmp_path, "hub") is False
    assert signalled == []


def test_root_tenant_is_stable_per_principal_and_separates_same_task_id(tmp_path, monkeypatch):
    app = SimpleNamespace(config={
        "security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
            "api_token_principal": "mcp-global",
            "allowed_roots": [str(tmp_path)],
        }
    })
    monkeypatch.setattr(http_server, "APP", app)
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    key = app.config["security"]["tenant_derivation_key"]
    tenant_a = http_server._derive_root_tenant("mcp-global", str(root_a.resolve()), key)
    tenant_b = http_server._derive_root_tenant("mcp-global", str(root_b.resolve()), key)
    assert tenant_a == http_server._derive_root_tenant("mcp-global", str(root_a.resolve()), key)
    assert tenant_a != tenant_b

    handler_a = _handler({})
    handler_a._authorization_tenant = tenant_a
    handler_b = _handler({})
    handler_b._authorization_tenant = tenant_b
    task_scope_a = http_server.Handler._bound_memory_scope_id(handler_a, http_server.AgentScope.TASK, None, "same-task")
    task_scope_b = http_server.Handler._bound_memory_scope_id(handler_b, http_server.AgentScope.TASK, None, "same-task")
    assert task_scope_a != task_scope_b

    task_a = SimpleNamespace(task_id="same-task", context=SimpleNamespace(
        repository_id=str(root_a.resolve()), session_id=tenant_a,
    ))
    assert http_server.Handler._task_matches_request(task_a, str(root_a.resolve()), tenant_a) is True
    assert http_server.Handler._task_matches_request(task_a, str(root_b.resolve()), tenant_b) is False

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config=app.config,
        agent_tasks=SimpleNamespace(get=lambda task_id: task_a if task_id == "same-task" else None),
    ))
    allowed = _handler({})
    assert http_server.Handler._request_task(allowed, "same-task", str(root_a.resolve()), tenant_a) is task_a
    # GET and update routes share this lookup gate.
    denied = _handler({})
    responses = []
    denied._send = lambda status, payload: responses.append((status, payload))
    assert http_server.Handler._request_task(denied, "same-task", str(root_b.resolve()), tenant_b) is None
    assert responses[0][0] == 404


def test_task_access_sandbox_fails_closed_without_allowed_roots(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    tenant = "tenant-bound"
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
        }
    }))
    handler = _handler({})

    task = SimpleNamespace(context=SimpleNamespace(
        repository_id=str(root.resolve()), session_id=tenant,
    ))
    rootless_task = SimpleNamespace(context=SimpleNamespace(
        repository_id="", session_id=tenant,
    ))
    tenantless_task = SimpleNamespace(context=SimpleNamespace(
        repository_id=str(root.resolve()), session_id="",
    ))

    assert http_server.Handler._root_sandbox_enabled(handler) is True
    assert http_server.Handler._task_matches_request(task, str(root.resolve()), tenant) is True
    assert http_server.Handler._task_matches_request(rootless_task, str(root.resolve()), tenant) is False
    assert http_server.Handler._task_matches_request(tenantless_task, str(root.resolve()), tenant) is False


def test_task_completion_rejects_missing_owner(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    task = SimpleNamespace(owner="", context=SimpleNamespace(
        repository_id=str(root.resolve()), session_id="api-token-default",
    ))
    app = SimpleNamespace(
        config={"server": {"state_dir": str(tmp_path)}},
        agent_tasks=SimpleNamespace(get=lambda _task_id: task),
        agent_verification=object(),
    )
    app.agent_tasks.state_store = SimpleNamespace(enabled=True)
    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        {"action": "complete", "task_id": "ownerless", "root": str(root)},
        app,
    )

    assert responses[0][0] == 403
    assert responses[0][1]["error_code"] == "task_owner_mismatch"


def test_root_scope_rejects_spoofed_header_or_body_tenant(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
            "api_token_principal": "mcp-global",
            "allowed_roots": [str(tmp_path)],
        }
    }))
    header_handler = _handler({"X-LocalAI-Tenant": "tenant-spoof"})
    header_errors = []
    header_handler._send = lambda status, payload: header_errors.append((status, payload))
    assert http_server.Handler._bind_root_tenant(header_handler, str(root)) is None
    assert header_errors[0][0] == 403

    body_handler = _handler({})
    body_errors = []
    body_handler._send = lambda status, payload: body_errors.append((status, payload))
    assert http_server.Handler._bind_memory_payload(body_handler, {
        "root": str(root), "scope": "repository", "tenant": "tenant-spoof",
    }) is False
    assert body_errors[0][0] == 403

    for candidate in (
        {"root": str(root), "scope": "repository", "record": {"tenant": "tenant-spoof"}},
        {"root": str(root), "scope": "repository", "provenance": {"tenant": "tenant-spoof"}},
        {"root": str(root), "scope": "repository", "record": {"provenance": {"tenant": "tenant-spoof"}}},
    ):
        handler = _handler({})
        errors = []
        handler._send = lambda status, payload: errors.append((status, payload))
        assert http_server.Handler._bind_memory_payload(handler, candidate) is False
        assert errors[0][0] == 403

    for candidate in (
        {"scope": "global", "tenant": "tenant-spoof"},
        {"scope": "global", "record": {"tenant": "tenant-spoof"}},
        {"scope": "global", "provenance": {"tenant": "tenant-spoof"}},
        {"scope": "global", "record": {"provenance": {"tenant": "tenant-spoof"}}},
    ):
        handler = _handler({})
        errors = []
        handler._send = lambda status, payload: errors.append((status, payload))
        assert http_server.Handler._bind_memory_payload(handler, candidate) is False
        assert errors[0][0] == 403


def test_root_scope_fails_closed_for_missing_nonexistent_and_symlink_roots(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
            "allowed_roots": [str(allowed)],
        }
    }))
    for requested in ("", str(tmp_path / "missing")):
        handler = _handler({})
        errors = []
        handler._send = lambda status, payload: errors.append((status, payload))
        assert http_server.Handler._bind_root_tenant(handler, requested) is None
        assert errors[0][0] == 403

    link = tmp_path / "allowed-link"
    try:
        link.symlink_to(allowed, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this host")
    handler = _handler({})
    errors = []
    handler._send = lambda status, payload: errors.append((status, payload))
    assert http_server.Handler._bind_root_tenant(handler, str(link)) is None
    assert errors[0][0] == 403

    http_server.APP.config["security"]["allowed_roots"] = []
    handler = _handler({})
    errors = []
    handler._send = lambda status, payload: errors.append((status, payload))
    assert http_server.Handler._bind_root_tenant(handler, str(allowed)) is None
    assert errors[0][0] == 403

    scoped_task_handler = _handler({})
    scoped_task_errors = []
    scoped_task_handler._send = lambda status, payload: scoped_task_errors.append((status, payload))
    assert http_server.Handler._bind_task_payload(scoped_task_handler, {
        "root": str(tmp_path / "missing-task-root"), "task_id": "task-a",
    }) is False
    assert scoped_task_errors[0][0] == 403


def test_fixed_api_token_tenant_remains_principal_namespace(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    derivation_key = "stable-test-derivation-secret-0123456789"
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {
            "api_token": "tenant-bound-token-long",
            "api_token_tenant": "tenant-alice",
            "tenant_derivation_key": derivation_key,
            "allowed_roots": [str(tmp_path)],
        }
    }))
    handler = _handler({
        "X-LocalAI-Token": "tenant-bound-token-long",
        "X-LocalAI-Tenant": "tenant-spoof",
    })
    assert http_server.Handler._authorized(handler, "read") is True
    assert http_server.Handler._tenant(handler) == "tenant-alice"
    assert handler._authorization_actor == "tenant-alice"

    untagged = _handler({})
    bound = http_server.Handler._bind_root_tenant(untagged, str(root))
    assert bound is not None
    assert bound[1] == http_server._derive_root_tenant("tenant-alice", str(root.resolve()), derivation_key)


def test_rootless_global_memory_is_forced_into_principal_scope(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {"api_token": "tenant-bound-token-long", "api_token_tenant": "tenant-alice"}
    }))
    handler = _handler({})
    payload = {"scope": "global", "key": "private"}
    assert http_server.Handler._bind_memory_payload(handler, payload) is True
    assert payload["scope"] == "session"
    assert payload["scope_id"] == "tenant-alice"
    assert payload["tenant"] == "tenant-alice"

    query = {"scope": ["global"]}
    query_handler = _handler({})
    assert http_server.Handler._bind_memory_query(query_handler, query) is True
    assert query["scope"] == ["session"]
    assert query["scope_id"] == ["tenant-alice"]
    assert query["session_id"] == ["tenant-alice"]
    assert query["tenant"] == ["tenant-alice"]

    denied = _handler({})
    responses = []
    denied._send = lambda status, data: responses.append((status, data))
    assert http_server.Handler._bind_memory_payload(denied, {"scope": "task", "task_id": "secret-task"}) is False
    assert responses[0][0] == 400


def test_debug_trace_request_contains_metadata_only(tmp_path):
    raw_root = str(tmp_path / "sensitive-project")
    captured = http_server.Handler._safe_debug_trace_request({
        "root": raw_root,
        "target_root": raw_root,
        "tenant": "sensitive-tenant",
        "context": {"repo_root": raw_root, "repository_id": raw_root, "tenant": "nested-tenant"},
    })
    serialized = json.dumps(captured)
    assert raw_root not in serialized
    assert "sensitive-tenant" not in serialized
    assert captured == {"capture_status": "metadata_only", "field_count": 4}


def test_agent_state_event_endpoints_fail_closed_without_scoping(monkeypatch):
    event_calls = []
    app = SimpleNamespace(agent_state=SimpleNamespace(
        enabled=True,
        events=lambda **kwargs: event_calls.append(kwargs) or [],
    ))
    events = _dispatch_get(monkeypatch, "/api/agent-state/events", app)
    stream = _dispatch_get(monkeypatch, "/api/agent-state/events/stream", app)

    assert events[0][0] == 403
    assert stream[0][0] == 403
    assert event_calls == []


def test_agent_state_status_does_not_return_global_task_ids(monkeypatch):
    app = SimpleNamespace(agent_tasks=SimpleNamespace(
        list_tasks=lambda: [SimpleNamespace(task_id="foreign-task", status=http_server.TaskStatus.ACTIVE)],
    ))

    responses = _dispatch_get(monkeypatch, "/api/status?detail=agent_state", app)

    assert responses[0][0] == 403
    assert "foreign-task" not in json.dumps(responses[0][1])


def test_memory_task_query_requires_existing_task_in_bound_root(tmp_path, monkeypatch):
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    tenant = http_server._derive_root_tenant(
        "principal", str(root_a.resolve()), "stable-test-derivation-secret-0123456789"
    )
    task = SimpleNamespace(task_id="known-task", context=SimpleNamespace(
        repository_id=str(root_a.resolve()), session_id=tenant,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
            "api_token_principal": "principal",
            "allowed_roots": [str(tmp_path)],
        }},
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "known-task" else None),
    ))

    missing = _handler({})
    missing_responses = []
    missing._send = lambda status, payload: missing_responses.append((status, payload))
    assert http_server.Handler._bind_memory_query(
        missing, {"root": [str(root_a)], "scope": ["task"], "task_id": ["unknown-task"]}
    ) is False
    assert missing_responses[0][0] == 404

    foreign = _handler({})
    foreign_responses = []
    foreign._send = lambda status, payload: foreign_responses.append((status, payload))
    assert http_server.Handler._bind_memory_query(
        foreign, {"root": [str(root_b)], "scope": ["task"], "task_id": ["known-task"]}
    ) is False
    assert foreign_responses[0][0] == 404


def test_verification_scope_requires_existing_task_owned_by_root(tmp_path, monkeypatch):
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    tenant_a = http_server._derive_root_tenant(
        "principal", str(root_a.resolve()), "stable-test-derivation-secret-0123456789"
    )
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=str(root_a.resolve()), session_id=tenant_a,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
        "api_token_principal": "principal",
        "allowed_roots": [str(tmp_path)],
    }}, agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None)))

    allowed = _handler({})
    assert http_server.Handler._bind_task_payload(allowed, {"root": str(root_a), "task_id": "task-a"}) is True
    assert http_server.Handler._require_scoped_task(allowed, "task-a") is task

    denied = _handler({})
    responses = []
    denied._send = lambda status, payload: responses.append((status, payload))
    assert http_server.Handler._bind_task_payload(denied, {"root": str(root_b), "task_id": "task-a"}) is True
    assert http_server.Handler._require_scoped_task(denied, "task-a") is None
    assert responses[0][0] == 404


@pytest.mark.parametrize("action", ["receipt", "completion"])
def test_verification_routes_reject_foreign_task_before_access(tmp_path, monkeypatch, action):
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    tenant_a = http_server._derive_root_tenant(
        "principal", str(root_a.resolve()), "stable-test-derivation-secret-0123456789"
    )
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=str(root_a.resolve()), session_id=tenant_a,
    ))
    calls = []
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
            "api_token_principal": "principal",
            "allowed_roots": [str(tmp_path)],
        }},
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None),
        recovery=SimpleNamespace(
            lookup=lambda *_args, **_kwargs: None,
            begin=lambda *_args, **_kwargs: None,
        ),
        agent_verification=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            record=lambda receipt: calls.append(("receipt", receipt)),
            completion=lambda *_args, **_kwargs: calls.append(("completion", _args)),
        ),
    )
    payload = {"action": action, "root": str(root_b), "task_id": "task-a"}
    if action == "receipt":
        payload["receipt"] = {"task_id": "task-a", "criterion": "owned task", "passed": True}

    responses = _dispatch_post(monkeypatch, "/api/agent-state/verification", payload, app)

    assert responses[0][0] == 404, responses[0]
    assert calls == []


@pytest.mark.parametrize("path", ["/api/memory/put", "/api/memory/get", "/api/memory/search"])
def test_legacy_memory_denies_shared_workspace_read_write_actions(tmp_path, monkeypatch, path):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
        "api_token_principal": "principal",
        "allowed_roots": [str(root)],
    }}))
    handler = _handler({})
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert http_server.Handler._bind_workspace_memory_payload(
        handler, path, {"root": str(root), "query": "private", "key": "k", "value": "v"}
    ) is False
    assert responses[0][0] == 403

    delete_handler = _handler({})
    assert http_server.Handler._bind_workspace_memory_payload(
        delete_handler, "/api/memory/delete", {"root": str(root), "key": "k"}
    ) is True
    assert delete_handler._authorization_tenant == http_server._derive_root_tenant(
        "principal", str(root.resolve()), "stable-test-derivation-secret-0123456789"
    )

    denied_root = _handler({})
    root_responses = []
    denied_root._send = lambda status, payload: root_responses.append((status, payload))
    assert http_server.Handler._bind_workspace_memory_payload(
        denied_root, "/api/memory/put", {"root": str(tmp_path), "key": "k", "value": "v"}
    ) is False
    assert root_responses[0][0] == 403


def test_debug_trace_captures_metadata_without_prompt_or_source_content():
    captured = http_server.Handler._safe_debug_trace_request({
        "source": "private source body",
        "prompt": "private prompt text",
        "query": "private query",
        "value": "private memory value",
        "text": "private transcript",
        "code": "private code",
        "context": {"repository_id": "C:/private/repository"},
    })

    serialized = json.dumps(captured)
    assert "private" not in serialized
    assert "C:/private/repository" not in serialized
    assert captured == {"capture_status": "metadata_only", "field_count": 7}


@pytest.mark.parametrize("action", ["reap", "reap_expired", "zombie_reap", "recover_zombie_tasks"])
def test_task_reaper_actions_forward_authenticated_root_scope(tmp_path, monkeypatch, action):
    root = tmp_path / "allowed"
    root.mkdir()
    calls = []
    principal = "principal"
    derivation_key = "stable-test-derivation-secret-0123456789"
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": derivation_key,
            "api_token_principal": principal,
            "allowed_roots": [str(root)],
        }},
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            reap_expired_heartbeats=lambda now=None, *, auto_recover=False, repo_root=None, tenant=None, task_id=None: calls.append((
                "reap", {"auto_recover": auto_recover, "repo_root": repo_root, "tenant": tenant, "task_id": task_id}
            )) or ["task-1"],
            recover_zombie_tasks=lambda now=None, *, repo_root=None, tenant=None, task_id=None: calls.append((
                "recover", {"repo_root": repo_root, "tenant": tenant, "task_id": task_id}
            )) or ["task-1"],
        ),
    )
    canonical_root = str(root.resolve())
    tenant = http_server._derive_root_tenant(principal, canonical_root, derivation_key)

    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        {
            "root": str(root),
            "action": action,
            "task_id": "task-1",
            "auto_recover": True,
            "tenant": "body-tenant-must-not-select-scope",
        },
        app,
        headers={
            "X-LocalAI-Token": "a-long-test-token-value",
            "X-LocalAI-Tenant": tenant,
        },
        authenticate=True,
    )

    assert responses[0][0] == 200
    assert responses[0][1]["reaped"] == ["task-1"]
    if action == "recover_zombie_tasks":
        assert calls == [("recover", {
            "repo_root": canonical_root,
            "tenant": tenant,
            "task_id": "task-1",
        })]
    else:
        assert calls == [("reap", {
            "auto_recover": True,
            "repo_root": canonical_root,
            "tenant": tenant,
            "task_id": "task-1",
        })]


def test_task_reaper_accepts_authenticated_principal_header_but_derives_root_tenant(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    calls = []
    principal = "principal"
    derivation_key = "stable-test-derivation-secret-0123456789"
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": derivation_key,
            "api_token_principal": principal,
            "allowed_roots": [str(root)],
        }},
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            reap_expired_heartbeats=lambda **kwargs: calls.append(kwargs) or ["task-1"],
        ),
    )
    canonical_root = str(root.resolve())
    expected_tenant = http_server._derive_root_tenant(principal, canonical_root, derivation_key)

    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        {"root": str(root), "action": "reap", "task_id": "task-1"},
        app,
        headers={
            "X-LocalAI-Token": "a-long-test-token-value",
            "X-LocalAI-Tenant": principal,
        },
        authenticate=True,
    )

    assert responses[0][0] == 200
    assert calls[0]["tenant"] == expected_tenant
    assert calls[0]["repo_root"] == canonical_root


def test_task_list_accepts_authenticated_principal_header_and_uses_derived_scope(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    principal = "principal"
    derivation_key = "stable-test-derivation-secret-0123456789"
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": derivation_key,
            "api_token_principal": principal,
            "allowed_roots": [str(root)],
        }},
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            list_tasks=lambda **_kwargs: [],
        ),
    )
    canonical_root = str(root.resolve())
    path = f"/api/agent-state/tasks?root={canonical_root}"

    responses = _dispatch_get(
        monkeypatch,
        path,
        app,
        headers={
            "X-LocalAI-Token": "a-long-test-token-value",
            "X-LocalAI-Tenant": principal,
        },
        authenticate=True,
    )

    assert responses[0][0] == 200
    assert responses[0][1]["tasks"] == []


def test_root_memory_accepts_authenticated_principal_header_and_derives_root_tenant(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    principal = "principal"
    derivation_key = "stable-test-derivation-secret-0123456789"
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "tenant_derivation_key": derivation_key,
        "api_token_principal": principal,
        "allowed_roots": [str(root)],
    }}))
    handler = _handler({"X-LocalAI-Tenant": principal})
    errors = []
    handler._send = lambda status, response: errors.append((status, response))
    payload = {"root": str(root), "scope": "global"}
    handler.headers["X-LocalAI-Token"] = "a-long-test-token-value"
    assert http_server.Handler._authorized(handler, "write") is True

    assert http_server.Handler._bind_memory_payload(handler, payload) is True
    assert errors == []
    assert payload["tenant"] == http_server._derive_root_tenant(
        principal, str(root.resolve()), derivation_key
    )


def test_root_agent_memory_fails_closed_without_configured_principal(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
        "allowed_roots": [str(root)],
    }}))
    handler = _handler({"X-LocalAI-Token": "a-long-test-token-value"})
    responses = []
    handler._send = lambda status, response: responses.append((status, response))
    payload = {"root": str(root), "scope": "global"}

    assert http_server.Handler._authorized(handler, "write") is True
    assert http_server.Handler._bind_memory_payload(handler, payload) is False
    assert responses[0][0] == 403


@pytest.mark.parametrize("action", ["curate_dataset", "curate_training_dataset"])
def test_task_dataset_curation_forwards_authenticated_root_scope(tmp_path, monkeypatch, action):
    root = tmp_path / "allowed"
    root.mkdir()
    calls = []
    principal = "principal"
    derivation_key = "stable-test-derivation-secret-0123456789"

    def curate_training_dataset(
        output_path,
        min_receipts=1,
        format="jsonl",
        *,
        repo_root=None,
        tenant=None,
        task_id=None,
    ):
        calls.append(((output_path,), {
            "min_receipts": min_receipts,
            "format": format,
            "repo_root": repo_root,
            "tenant": tenant,
            "task_id": task_id,
        }))
        return {"success": True}

    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": derivation_key,
            "api_token_principal": principal,
            "allowed_roots": [str(root)],
        }},
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            curate_training_dataset=curate_training_dataset,
        ),
    )
    canonical_root = str(root.resolve())
    tenant = http_server._derive_root_tenant(principal, canonical_root, derivation_key)

    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        {
            "root": str(root),
            "action": action,
            "task_id": "task-1",
            "output_path": "dataset.jsonl",
            "min_receipts": 3,
            "format": "jsonl",
        },
        app,
        headers={"X-LocalAI-Tenant": tenant},
    )

    assert responses[0][0] == 200
    assert calls == [(("dataset.jsonl",), {
        "min_receipts": 3,
        "format": "jsonl",
        "repo_root": canonical_root,
        "tenant": tenant,
        "task_id": "task-1",
    })]


@pytest.mark.parametrize("payload,headers", [
    ({"action": "reap"}, {}),
    ({"action": "curate_dataset", "root": "C:/outside"}, {}),
    ({"action": "reap", "root": "{root}"}, {"X-LocalAI-Tenant": "header-tenant"}),
])
def test_scoped_task_operations_reject_invalid_root_or_tenant_before_store_mutation(
    tmp_path, monkeypatch, payload, headers
):
    root = tmp_path / "allowed"
    root.mkdir()
    calls = []
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
            "api_token_principal": "principal",
            "allowed_roots": [str(root)],
        }},
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            reap_expired_heartbeats=lambda **kwargs: calls.append(kwargs),
            curate_training_dataset=lambda *args, **kwargs: calls.append((args, kwargs)),
        ),
    )
    resolved_payload = {key: (str(root) if value == "{root}" else value) for key, value in payload.items()}

    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        resolved_payload,
        app,
        headers=headers,
    )

    assert responses[0][0] == 403
    assert calls == []


@pytest.mark.parametrize("case", ["wrong_token", "wrong_tenant_header", "missing_principal_binding"])
def test_scoped_task_routes_fail_closed_on_authentication_binding_mismatch(
    tmp_path, monkeypatch, case
):
    root = tmp_path / "allowed"
    root.mkdir()
    principal = "principal"
    derivation_key = "stable-test-derivation-secret-0123456789"
    security = {
        "api_token": "a-long-test-token-value",
        "tenant_derivation_key": derivation_key,
        "allowed_roots": [str(root)],
    }
    if case != "missing_principal_binding":
        security["api_token_principal"] = principal
    app = SimpleNamespace(
        config={"security": security},
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            reap_expired_heartbeats=lambda **_kwargs: pytest.fail("scope mismatch reached task store"),
        ),
    )
    expected_tenant = http_server._derive_root_tenant(
        principal, str(root.resolve()), derivation_key
    )
    headers = {
        "X-LocalAI-Token": "wrong-token" if case == "wrong_token" else security["api_token"],
        "X-LocalAI-Tenant": (
            "wrong-tenant" if case == "wrong_tenant_header" else expected_tenant
        ),
    }

    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        {"root": str(root), "action": "reap", "tenant": "body-tenant"},
        app,
        headers=headers,
        authenticate=True,
    )

    expected_status = 401 if case == "wrong_token" else 403
    assert responses[0][0] == expected_status


@pytest.mark.parametrize("path", [
    "/api/agent-state/events/delta",
    "/api/agent-state/swarm",
    "/api/agent-state/swarm/swarm-id",
])
def test_unscoped_agent_state_get_routes_deny_before_store_access(monkeypatch, path):
    calls = []
    spy = _store_spy(calls)
    app = SimpleNamespace(
        agent_state=spy,
        agent_blackboard=spy,
        swarm=spy,
        agent_tasks=spy,
        agent_incidents=spy,
        agent_learning=spy,
    )

    responses = _dispatch_get(monkeypatch, path, app)

    assert responses[0][0] == 403
    assert calls == []


@pytest.mark.parametrize(("path", "action"), [
    ("/api/agent-state/incidents", "decision"),
    ("/api/agent-state/incidents", "record"),
    ("/api/agent-state/incidents", "resolve"),
    ("/api/agent-state/incidents", "ignore"),
    ("/api/agent-state/incidents", "unignore"),
    ("/api/agent-state/incidents", "find_regressions"),
    ("/api/agent-state/incidents", "find"),
    ("/api/agent-state/incidents", "list"),
    ("/api/agent-state/learning", "create_candidate"),
    ("/api/agent-state/learning", "promote"),
    ("/api/agent-state/learning", "observe"),
    ("/api/agent-state/learning", "list"),
    ("/api/agent-state/cleanup", "cleanup"),
    ("/api/agent-state/blackboard", "update"),
    ("/api/agent-state/blackboard", "put"),
    ("/api/agent-state/blackboard", "blackboard_update"),
    ("/api/agent-state/blackboard", "get"),
    ("/api/agent-state/blackboard", "read"),
    ("/api/agent-state/blackboard", "blackboard_get"),
    ("/api/agent-state/blackboard", "list"),
    ("/api/agent-state/blackboard", "blackboard_list"),
    ("/api/agent-state/blackboard", "merge"),
    ("/api/agent-state/blackboard", "blackboard_merge"),
    ("/api/agent-state/blackboard", "delete"),
    ("/api/agent-state/blackboard", "remove"),
    ("/api/agent-state/blackboard", "blackboard_delete"),
    ("/api/agent-state/swarm/dispatch", "dispatch"),
    ("/api/agent-state/swarm/step", "step"),
    ("/api/agent-state/swarm/cancel", "cancel"),
    ("/api/agent-state/events/delta", "import"),
])
def test_unscoped_agent_state_post_routes_deny_before_store_access(monkeypatch, path, action):
    calls = []
    spy = _store_spy(calls)
    app = SimpleNamespace(
        agent_state=spy,
        agent_blackboard=spy,
        swarm=spy,
        agent_tasks=spy,
        agent_incidents=spy,
        agent_learning=spy,
        agent_context=spy,
    )

    responses = _dispatch_post(monkeypatch, path, {"action": action}, app)

    assert responses[0][0] == 403
    assert calls == []


def test_debug_trace_never_persists_raw_error_or_exception_text(monkeypatch):
    finished = []
    app = SimpleNamespace(debug_traces=SimpleNamespace(
        finish=lambda *args, **kwargs: finished.append((args, kwargs)) or True,
    ))
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler({})
    handler._debug_trace_id = "trace-id"

    http_server.Handler._finish_debug_trace(
        handler,
        500,
        {"success": False, "error": "private response exception text"},
        error="private traceback and source prompt",
    )

    stored = json.dumps(finished)
    assert "private response exception text" not in stored
    assert "private traceback and source prompt" not in stored
    assert "traceback" not in stored.lower()


def test_context_compile_binds_existing_task_root_without_changing_task_id_contract(tmp_path, monkeypatch):
    from local_ai_hub.task_context import build_context_request

    root = tmp_path / "repo"
    root.mkdir()
    tenant = http_server._derive_root_tenant(
        "principal", str(root.resolve()), "stable-test-derivation-secret-0123456789"
    )
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=str(root.resolve()), session_id=tenant,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
        "api_token_principal": "principal",
        "allowed_roots": [str(root)],
    }}, agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None)))
    handler = _handler({"X-LocalAI-Tenant": "principal"})
    payload = {"action": "compile", "task_id": "task-a"}

    assert http_server.Handler._bind_context_payload(handler, payload) is True
    request = build_context_request(payload, tenant=http_server.Handler._tenant(handler))
    assert request.task_id == "task-a"
    assert request.root == str(root.resolve())
    assert request.tenant == tenant
    assert request.scoped_task_only is True


def test_context_compile_rejects_foreign_or_unknown_task_before_compile(tmp_path, monkeypatch):
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    tenant_a = http_server._derive_root_tenant(
        "principal", str(root_a.resolve()), "stable-test-derivation-secret-0123456789"
    )
    task_a = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=str(root_a.resolve()), session_id=tenant_a,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
        "api_token_principal": "principal",
        "allowed_roots": [str(tmp_path)],
    }}, agent_tasks=SimpleNamespace(get=lambda task_id: task_a if task_id == "task-a" else None)))

    for payload in ({"task_id": "missing"}, {"task_id": "task-a", "root": str(root_b)}):
        handler = _handler({})
        responses = []
        handler._send = lambda status, value: responses.append((status, value))
        assert http_server.Handler._bind_context_payload(handler, payload) is False
        assert responses[0][0] in {403, 404}


def test_task_event_reads_allow_only_owned_task_stream(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    tenant = http_server._derive_root_tenant(
        "principal", str(root.resolve()), "stable-test-derivation-secret-0123456789"
    )
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=str(root.resolve()), session_id=tenant,
    ))
    calls = []
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
            "api_token_principal": "principal",
            "allowed_roots": [str(root)],
        }},
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None),
        agent_state=SimpleNamespace(enabled=True, events=lambda **kwargs: calls.append(kwargs) or []),
    )
    handler = _handler({"X-LocalAI-Tenant": "principal"}, path=(
        f"/api/agent-state/events?root={root}&stream_id=task%3Atask-a"
    ))
    monkeypatch.setattr(http_server, "APP", app)
    handler._begin_trace = lambda *_args: None
    handler._require_authorized = lambda *_args, **_kwargs: True
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    http_server.Handler.do_GET(handler)

    assert responses[0][0] == 200
    assert calls == [{"stream_id": "task:task-a", "after_seq": 0, "limit": 100}]


def test_task_blackboard_access_requires_owned_task_board(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    tenant = http_server._derive_root_tenant(
        "principal", str(root.resolve()), "stable-test-derivation-secret-0123456789"
    )
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=str(root.resolve()), session_id=tenant,
    ))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "tenant_derivation_key": "stable-test-derivation-secret-0123456789",
        "api_token_principal": "principal",
        "allowed_roots": [str(root)],
    }}, agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None)))

    allowed = _handler({})
    payload = {"action": "update", "root": str(root), "task_id": "task-a", "board_id": "task:task-a"}
    assert http_server.Handler._bind_task_board_payload(allowed, payload) is True

    denied = _handler({})
    responses = []
    denied._send = lambda status, value: responses.append((status, value))
    assert http_server.Handler._bind_task_board_payload(
        denied, {"action": "update", "root": str(root), "task_id": "task-a", "board_id": "global"}
    ) is False
    assert responses[0][0] == 403

def test_supervisor_restart_gracefully_reaps_owned_hub_before_respawn(tmp_path, monkeypatch):
    headless = (
        "[headless]\nmanage_ollama = false\n"
        "startup_grace_seconds = 0.5\nrestart_backoff_initial_seconds = 0.1\n"
        "restart_backoff_max_seconds = 0.1\n"
    )
    module, supervisor, _state_dir = _supervisor_for_lifecycle(tmp_path, monkeypatch, headless=headless)
    clock = [0.0]

    def identity(pid):
        return {
            "pid": pid,
            "executable": "/usr/bin/python3",
            "creation_identity": pid,
            "creation_identity_type": "test_start_time",
        }

    monkeypatch.setattr(process_utils, "process_identity", identity)
    monkeypatch.setattr(module, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(supervisor, "hub_online", lambda: False)
    monkeypatch.setattr(supervisor, "hub_ready", lambda: False)
    monkeypatch.setattr(supervisor, "write_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + max(seconds, 0.3)))
    spawns = []
    killed = []

    def spawn():
        pid = 4242 + len(spawns) * 100
        child = SimpleNamespace(pid=pid, poll=lambda: None, wait=lambda **_kwargs: None, kill=lambda: killed.append(("kill", pid)))
        spawns.append(child)
        if len(spawns) == 2:
            supervisor.stopping = True
        return child

    terminated = []
    monkeypatch.setattr(supervisor, "spawn_hub", spawn)
    monkeypatch.setattr(module, "terminate_process_handle", lambda child, _pidfd, **kwargs: terminated.append((child.pid, kwargs.get("grace_seconds"))) or True)
    monkeypatch.setattr(module, "open_pidfd", lambda _pid: None)

    assert supervisor.run() == 0
    assert len(spawns) == 2
    assert terminated[:2] == [(4242, 5.0), (4342, 5.0)]
    assert all(item[0] != "kill" for item in killed)


def test_disabled_supervisor_stays_stopped(tmp_path, monkeypatch):
    module, supervisor, _state_dir = _supervisor_for_lifecycle(tmp_path, monkeypatch)
    supervisor.disabled_path.write_text("disabled by operator", encoding="utf-8")
    monkeypatch.setattr(supervisor, "acquire", lambda: pytest.fail("disabled supervisor acquired lock"))
    monkeypatch.setattr(supervisor, "spawn_hub", lambda: pytest.fail("disabled supervisor spawned hub"))

    assert supervisor.run() == 0
    assert supervisor.disabled_path.read_text(encoding="utf-8") == "disabled by operator"


def test_managed_service_start_does_not_duplicate_existing_supervisor(tmp_path, monkeypatch):
    from local_ai_hub import config as config_module

    state_dir = tmp_path / "service-state"
    monkeypatch.setattr(config_module, "load_config", lambda *_args: {
        "server": {"state_dir": str(state_dir), "port": 11435},
        "headless": {},
        "_config_path": str(tmp_path / "config.toml"),
    })
    service_path = Path(__file__).parents[1] / "tools" / "service.py"
    spec = importlib.util.spec_from_file_location("test_service_managed_start", service_path)
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    service.DISABLED.write_text("disabled", encoding="utf-8")
    monkeypatch.setattr(service, "supervisor_pid", lambda: 4242)
    spawned = []
    monkeypatch.setattr(service, "spawn_detached", lambda: spawned.append(True))

    service.native_start()

    assert service.MANAGED.exists()
    assert service.DISABLED.exists() is False
    assert spawned == []


def test_service_fallback_spawn_preserves_active_config(tmp_path, monkeypatch):
    service = _load_service_for_test(monkeypatch, tmp_path)
    active_config = tmp_path / "selected-config.toml"
    active_config.write_text("[server]\n", encoding="utf-8")
    service._ACTIVE_CONFIG_ARG = str(active_config)
    monkeypatch.setattr(service, "supervisor_pid", lambda: 0)
    monkeypatch.setattr(service.shutil, "which", lambda _name: None)
    captured = {}
    monkeypatch.setattr(service.subprocess, "Popen", lambda args, **kwargs: captured.update(args=args, kwargs=kwargs))

    service.spawn_detached()

    assert captured["kwargs"]["env"]["LOCAL_AI_CONFIG"] == str(active_config)
    assert captured["args"][-1] == "local_ai_hub.supervisor"


def test_supervisor_spawn_uses_its_active_config(tmp_path, monkeypatch):
    module, supervisor, _state_dir = _supervisor_for_lifecycle(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(module.subprocess, "Popen", lambda args, **kwargs: captured.update(args=args, kwargs=kwargs))

    supervisor.spawn_hub()

    assert captured["kwargs"]["env"]["LOCAL_AI_CONFIG"] == supervisor.config_path
    assert captured["args"][-1] == "local_ai_hub.http_server"


def _install_fake_darwin_libproc(monkeypatch, start_times=(123456789, 123456789), *, command="python3"):
    calls = {"pidinfo": 0}

    class NativeFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def pidinfo(pid, flavor, _arg, out, size):
        assert flavor == 3
        assert size == process_utils.ctypes.sizeof(process_utils._DARWIN_BSDINFO)
        index = min(calls["pidinfo"], len(start_times) - 1)
        calls["pidinfo"] += 1
        info = process_utils.ctypes.cast(out, process_utils.ctypes.POINTER(process_utils._DARWIN_BSDINFO)).contents
        info.pbi_pid = pid
        info.pbi_comm = command.encode("utf-8")
        info.pbi_start_tvsec, info.pbi_start_tvusec = divmod(start_times[index], 1_000_000)
        return size

    def pidpath(_pid, out, size):
        path = b"/usr/bin/python3\0"
        process_utils.ctypes.memmove(out, path, len(path))
        return len(path) - 1 if len(path) <= size else 0

    libproc = SimpleNamespace(
        proc_pidinfo=NativeFunction(pidinfo),
        proc_pidpath=NativeFunction(pidpath),
    )
    monkeypatch.setattr(process_utils.ctypes, "CDLL", lambda *_args, **_kwargs: libproc)
    return calls


def test_process_identity_uses_darwin_start_time_and_executable(tmp_path, monkeypatch):
    _install_fake_darwin_libproc(monkeypatch, (123456789, 123456789))
    monkeypatch.setattr(process_utils.sys, "platform", "darwin")
    real_os = process_utils.os
    monkeypatch.setattr(process_utils, "os", SimpleNamespace(name="posix", fsdecode=real_os.fsdecode, path=real_os.path))

    identity = process_utils.process_identity(4242)

    assert identity == {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "command": "python3",
        "creation_identity": 123456789,
        "creation_identity_type": "darwin_proc_bsdinfo_start_time_usec",
    }
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: identity)
    record = process_utils.process_owner_record(4242, tmp_path / "state", "supervisor")
    assert record["command"] == "python3"


def test_darwin_identity_fails_closed_when_pid_reused_during_probe(monkeypatch):
    calls = _install_fake_darwin_libproc(monkeypatch, (123456789, 123456790))

    assert process_utils._darwin_process_identity(4242) is None
    assert calls["pidinfo"] == 2


def test_darwin_owner_state_rejects_reused_pid_and_changed_command(tmp_path, monkeypatch):
    record = {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "command": "python3",
        "creation_identity": 123456789,
        "creation_identity_type": "darwin_proc_bsdinfo_start_time_usec",
        "state_dir": str((tmp_path / "state").resolve()),
        "role": "supervisor",
    }
    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "command": "other-command",
        "creation_identity": 123456789,
        "creation_identity_type": "darwin_proc_bsdinfo_start_time_usec",
    })

    assert process_utils.process_owner_state(record, tmp_path / "state", "supervisor") == "unknown"

    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: {
        "pid": 4242,
        "executable": "/usr/bin/other-python",
        "command": "python3",
        "creation_identity": 123456789,
        "creation_identity_type": "darwin_proc_bsdinfo_start_time_usec",
    })
    assert process_utils.process_owner_state(record, tmp_path / "state", "supervisor") == "unknown"

    monkeypatch.setattr(process_utils, "process_identity", lambda _pid: {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "command": "python3",
        "creation_identity": 123456790,
        "creation_identity_type": "darwin_proc_bsdinfo_start_time_usec",
    })
    assert process_utils.process_owner_state(record, tmp_path / "state", "supervisor") == "stale"


def test_config_rejects_nonliteral_loopback_bind_and_remote_opt_in(tmp_path):
    from local_ai_hub.config import ConfigError, load_config

    config = tmp_path / "config.toml"
    for bind in ("0.0.0.0", "localhost", "::1", " 127.0.0.1 "):
        config.write_text(
            f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\nbind = "{bind}"\n'
            '[security]\nallow_remote = false\napi_token = "long-secure-token-value-12345"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="server.bind must be 127.0.0.1"):
            load_config(str(config))

    config.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\nbind = "127.0.0.1"\n'
        '[security]\nallow_remote = true\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="security.allow_remote is unsupported"):
        load_config(str(config))


def _load_service_for_test(monkeypatch, state_dir: Path):
    from local_ai_hub import config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda *_args, **_kwargs: {
        "server": {"state_dir": str(state_dir), "port": 11435},
        "headless": {},
        "_config_path": str(state_dir / "config.toml"),
    })
    service_path = Path(__file__).parents[1] / "tools" / "service.py"
    spec = importlib.util.spec_from_file_location("test_service_stop_contract", service_path)
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service


def test_native_stop_reports_managed_ollama_failure(tmp_path, monkeypatch):
    service = _load_service_for_test(monkeypatch, tmp_path)
    monkeypatch.setattr(service, "mark_disabled", lambda _disabled: None)
    monkeypatch.setattr(service, "request_graceful_hub_stop", lambda: False)
    monkeypatch.setattr(service, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(service, "kill_supervisor", lambda: True)
    monkeypatch.setattr(service, "kill_hub", lambda: True)
    monkeypatch.setattr(service, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(service, "stop_managed_ollama", lambda: False)

    result = service.native_stop()

    assert result["success"] is False
    assert result["stopped"] is False
    assert result["managed_ollama_stopped"] is False
    assert "managed_ollama_stop_unverified" in result["errors"]


@pytest.mark.parametrize("fallback_probe_exit, expected_success", [(0, True), (1, False), (124, False)])
def test_native_stop_windows_fallback_requires_verified_registration(tmp_path, monkeypatch, fallback_probe_exit, expected_success):
    service = _load_service_for_test(monkeypatch, tmp_path)
    monkeypatch.setattr(service, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(service.shutil, "which", lambda _name: "powershell.exe")
    disabled = []
    monkeypatch.setattr(service, "mark_disabled", lambda value: disabled.append(value))
    monkeypatch.setattr(service, "request_graceful_hub_stop", lambda: False)
    monkeypatch.setattr(service, "kill_supervisor", lambda: True)
    monkeypatch.setattr(service, "kill_hub", lambda: True)
    monkeypatch.setattr(service, "find_listening_pid", lambda _port: None)
    monkeypatch.setattr(service, "stop_managed_ollama", lambda: True)

    def manager_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, fallback_probe_exit if argv[0] == "powershell.exe" else 1)

    monkeypatch.setattr(service, "run", manager_run)
    result = service.native_stop()

    assert disabled == [True]
    assert result["stopped"] is True
    assert result["success"] is expected_success
    assert result["errors"] == ([] if expected_success else ["schtasks_stop_failed"])
    if expected_success:
        assert result["service_manager"]["backend"] == "windows-user-startup"


def test_service_manager_timeout_is_bounded_and_structured(tmp_path, monkeypatch):
    service = _load_service_for_test(monkeypatch, tmp_path)
    seen = {}

    def timeout_run(argv, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(service.subprocess, "run", timeout_run)
    result = service.run(["systemctl", "--user", "stop", "local-ai-hub.service"], timeout=0.25)
    manager = service._service_manager_stop_result("systemctl", result)

    assert seen["timeout"] == 1.0
    assert manager == {
        "backend": "systemctl",
        "returncode": 124,
        "success": False,
        "timed_out": True,
        "reason": "systemctl_stop_timeout",
    }


def test_direct_hub_serve_rejects_unowned_parent_before_bind(tmp_path, monkeypatch):
    monkeypatch.setattr(http_server, "load_config", lambda _path: {
        "server": {"state_dir": str(tmp_path)},
    })
    monkeypatch.setattr(http_server, "validate_network_security", lambda _config: None)
    monkeypatch.setattr(
        http_server,
        "LocalAIHTTPServer",
        lambda *_args, **_kwargs: pytest.fail("unowned direct Hub must fail before bind"),
    )

    with pytest.raises(RuntimeError, match="identity-verified supervisor"):
        http_server.serve(None)


def test_supervisor_owner_publication_race_waits_for_identity_record(tmp_path, monkeypatch):
    state_dir = tmp_path.resolve()
    owner_pid = process_utils.process_parent_pid()
    assert owner_pid is not None

    def owner_state(owner, actual_state_dir, role):
        assert actual_state_dir == state_dir
        assert role == "supervisor"
        return "owned" if owner.get("pid") == owner_pid else "unknown"

    monkeypatch.setattr(http_server, "process_owner_state", owner_state)

    def publish_owner():
        time.sleep(0.05)
        (state_dir / "supervisor.owner.json").write_text(
            json.dumps({"pid": owner_pid}), encoding="utf-8",
        )

    publisher = threading.Thread(target=publish_owner)
    publisher.start()
    try:
        http_server._require_owned_supervisor_parent(state_dir)
    finally:
        publisher.join(timeout=1.0)
    assert not publisher.is_alive()


@pytest.mark.skipif(os.name != "nt", reason="Windows hidden process-group parent PID")
def test_process_parent_pid_tracks_direct_parent_across_hidden_process_groups():
    source_root = Path(__file__).parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    child_code = (
        "import time; "
        "from local_ai_hub.process_utils import process_parent_pid; "
        "time.sleep(0.2); "
        "print(process_parent_pid())"
    )
    wrapper_code = "\n".join((
        "import os, subprocess, sys",
        "from local_ai_hub.process_utils import hidden_run_kwargs, process_parent_pid",
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **hidden_run_kwargs(detached=True))",
        "snapshot_parent = process_parent_pid(child.pid)",
        "stdout, stderr = child.communicate(timeout=5)",
        "if child.returncode != 0: raise SystemExit(stderr)",
        "child_parent = int(stdout.strip())",
        "print(f'{os.getpid()}\\t{child.pid}\\t{child_parent}\\t{snapshot_parent}')",
    ))
    wrapper = subprocess.run(
        [sys.executable, "-c", wrapper_code], cwd=source_root, env=env,
        capture_output=True, timeout=10,
        **process_utils.hidden_run_kwargs(text=True),
    )
    assert wrapper.returncode == 0, wrapper.stderr
    wrapper_pid, child_pid, child_parent_pid, snapshot_parent = (
        int(value) for value in wrapper.stdout.strip().split("\t")
    )
    assert child_pid != wrapper_pid
    assert snapshot_parent == wrapper_pid
    assert child_parent_pid == wrapper_pid


def test_hub_pid_resolver_emits_only_identity_verified_owner(tmp_path, monkeypatch):
    resolver_path = Path(__file__).parents[1] / "tools" / "resolve_hub_pids.py"
    spec = importlib.util.spec_from_file_location("test_hub_pid_resolver", resolver_path)
    resolver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resolver)
    state_dir = tmp_path.resolve()
    owner = {
        "pid": 4242,
        "executable": "/usr/bin/python3",
        "creation_identity": 77,
        "creation_identity_type": "test_start_time",
        "state_dir": str(state_dir),
        "role": "hub",
    }
    (state_dir / "hub.owner.json").write_text(json.dumps(owner), encoding="utf-8")
    (state_dir / "hub.pid").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(resolver, "load_config", lambda _path: {"server": {"state_dir": str(state_dir)}})
    states = []

    def owner_state(actual_owner, actual_state_dir, role):
        states.append((actual_owner, actual_state_dir, role))
        return "owned"

    monkeypatch.setattr(resolver, "process_owner_state", owner_state)
    assert resolver._owned_hub_pid("unused-config.toml") == 4242
    assert states[-1] == (owner, state_dir, "hub")

    monkeypatch.setattr(resolver, "process_owner_state", lambda *_args: "unknown")
    assert resolver._owned_hub_pid("unused-config.toml") is None


def test_async_job_trace_persists_metadata_only_request_and_response(tmp_path, monkeypatch):
    from local_ai_hub import async_jobs
    from local_ai_hub.async_jobs import AsyncJobManager
    from local_ai_hub.debug_traces import DebugTraceStore

    snapshot = SimpleNamespace(mode="active", degraded=False, revision=0)
    monkeypatch.setattr(async_jobs, "load_operational_mode", lambda _state_dir: snapshot, raising=False)
    monkeypatch.setattr(async_jobs, "operational_mode_gate_error", lambda _snapshot: None, raising=False)
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "async_jobs": {"wait_max_seconds": 3},
        "debug_traces": {"enabled": True},
    }
    traces = DebugTraceStore(config)

    class Artifacts:
        def put(self, _content, _tenant, _kind):
            return "artifact-1"

    manager = AsyncJobManager(
        config,
        scheduler=object(),
        artifacts=Artifacts(),
        executor=lambda _action, _payload, _tenant: {
            "success": True,
            "answer": "private response text",
        },
        debug_traces=traces,
    )
    try:
        submitted = manager.submit(
            "tenant-a",
            "reason",
            {"task": "private prompt text", "context": "private source text"},
        )
        assert manager.wait("tenant-a", submitted["job_id"], 3)["state"] == "done"
        detail = traces.detail(submitted["trace_id"])
        serialized = json.dumps(detail, ensure_ascii=False)

        assert detail["session"]["request"] == {"capture_status": "metadata_only", "field_count": 2}
        assert "private prompt text" not in serialized
        assert "private source text" not in serialized
        assert "private response text" not in serialized
    finally:
        manager.close()
