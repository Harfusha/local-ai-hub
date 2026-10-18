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


def _project_state(root: Path, state_dir: Path):
    from local_ai_hub.project_config import resolve_project_context

    state_dir.mkdir(parents=True, exist_ok=True)
    state = SimpleNamespace(db_path=str(state_dir / "agent_state.sqlite3"))
    return state, resolve_project_context(root, state_dir).coordination_id


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
        handler.server = SimpleNamespace(check_rate_limit=lambda: True)
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
        handler.server = SimpleNamespace(check_rate_limit=lambda: True)
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


def test_api_token_permissions_apply_to_installation_owner(monkeypatch):
    app = SimpleNamespace(config={
        "security": {
            "api_token": "alice-user-credential-long",
            "api_token_permissions": ["read", "write"],
        }
    })
    monkeypatch.setattr(http_server, "APP", app)
    handler = _handler({
        "X-LocalAI-Token": "alice-user-credential-long",
    }, method="POST", path="/api/delegate")

    assert http_server.Handler._authorized(handler, "write") is True
    assert handler._authorization_actor == "api_token"
    assert handler._authorization_permissions == frozenset({"read", "write"})


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
    }, method="POST", path="/api/admin/mode")
    invalid = _handler({
        "X-LocalAI-Token": "wrong-credential",
    })

    assert http_server.Handler._authorized(valid, "admin") is False
    assert valid._authorization_status == 403
    assert http_server.Handler._authorized(invalid, "read") is False
    assert invalid._authorization_status == 401


def test_retired_tenant_header_is_rejected_even_with_valid_token(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "valid-owner-token",
    }}))
    handler = _handler({
        "X-LocalAI-Token": "valid-owner-token",
        "X-LocalAI-Tenant": "retired-value",
    })
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert http_server.Handler._reject_retired_tenant_headers(handler) is False
    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "retired_tenant_header"


@pytest.mark.parametrize("header", ["X-LocalAI-Tenant", "X-Tenant-ID"])
def test_each_retired_tenant_header_alias_is_rejected(header):
    handler = _handler({header: "retired-value"})
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))
    assert http_server.Handler._reject_retired_tenant_headers(handler) is False
    assert responses[0][1]["error_code"] == "retired_tenant_header"


def test_retired_tenant_body_field_is_rejected():
    handler = _handler({})
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert http_server.Handler._reject_identity_fields(handler, {"tenant": "retired-value"}) is False
    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "retired_tenancy_field"


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


def test_config_rejects_retired_tenant_auth_settings(tmp_path):
    from local_ai_hub.config import ConfigError, load_config

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

    with pytest.raises(ConfigError, match="api_token_tenant was removed"):
        load_config(str(config))


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

    monkeypatch.setattr(config_module, "load_config", lambda *_args, **_kwargs: {
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

    monkeypatch.setattr(config_module, "load_config", lambda *_args, **_kwargs: {
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


def test_task_lookup_is_bound_to_repository_root(tmp_path, monkeypatch):
    app = SimpleNamespace(config={
        "security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(tmp_path)],
        }
    })
    monkeypatch.setattr(http_server, "APP", app)
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    _state, coordination_id = _project_state(root_a, tmp_path / "state")
    task_a = SimpleNamespace(task_id="same-task", context=SimpleNamespace(
        repository_id=coordination_id, session_id="session-a",
    ), checkpoint=SimpleNamespace(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(root_a.resolve())},
    }))
    assert http_server.Handler._task_matches_request(task_a, str(root_a.resolve())) is True
    assert http_server.Handler._task_matches_request(task_a, str(root_b.resolve())) is False

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config=app.config,
        agent_tasks=SimpleNamespace(get=lambda task_id: task_a if task_id == "same-task" else None),
    ))
    allowed = _handler({})
    assert http_server.Handler._request_task(allowed, "same-task", str(root_a.resolve())) is task_a
    # GET and update routes share this lookup gate.
    denied = _handler({})
    responses = []
    denied._send = lambda status, payload: responses.append((status, payload))
    assert http_server.Handler._request_task(denied, "same-task", str(root_b.resolve())) is None
    assert responses[0][0] == 404


def test_task_access_sandbox_fails_closed_without_allowed_roots(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _state, coordination_id = _project_state(root, tmp_path / "state")
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {
            "api_token": "a-long-test-token-value",
        }
    }))
    handler = _handler({})

    task = SimpleNamespace(
        context=SimpleNamespace(repository_id=coordination_id, session_id="session-a"),
        checkpoint=SimpleNamespace(state_data={
            "_agent_task_scope": {"version": 2, "repo_root": str(root.resolve())},
        }),
    )
    rootless_task = SimpleNamespace(
        context=SimpleNamespace(repository_id="", session_id="session-a"),
        checkpoint=SimpleNamespace(state_data={}),
    )

    blocked = _handler({})
    blocked_response = []
    blocked._send = lambda status, payload: blocked_response.append((status, payload))
    assert http_server.Handler._bind_root(blocked, str(root.resolve())) is None
    assert blocked_response[0][0] == 403
    assert http_server.Handler._task_matches_request(task, str(root.resolve())) is True
    assert http_server.Handler._task_matches_request(rootless_task, str(root.resolve())) is False


def test_task_completion_rejects_missing_owner(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    agent_state, coordination_id = _project_state(root, tmp_path / "state")
    task = SimpleNamespace(
        owner="",
        context=SimpleNamespace(repository_id=coordination_id, session_id="session-test"),
        checkpoint=SimpleNamespace(state_data={
            "_agent_task_scope": {"version": 2, "repo_root": str(root.resolve())},
        }),
    )
    app = SimpleNamespace(
        config={"server": {"state_dir": str(tmp_path)}},
        agent_state=agent_state,
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


def test_root_scope_rejects_retired_tenant_header_and_body_fields(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(tmp_path)],
        }
    }))
    header_handler = _handler({"X-LocalAI-Tenant": "tenant-spoof"})
    header_errors = []
    header_handler._send = lambda status, payload: header_errors.append((status, payload))
    assert http_server.Handler._reject_retired_tenant_headers(header_handler) is False
    assert header_errors[0][0] == 400

    body_handler = _handler({})
    body_errors = []
    body_handler._send = lambda status, payload: body_errors.append((status, payload))
    assert http_server.Handler._reject_identity_fields(body_handler, {
        "root": str(root), "tenant": "retired-value",
    }) is False
    assert body_errors[0][0] == 400

    for candidate in (
        {"root": str(root), "record": {"tenant": "retired-value"}},
        {"root": str(root), "provenance": {"tenant": "retired-value"}},
        {"root": str(root), "record": {"provenance": {"tenant": "retired-value"}}},
    ):
        handler = _handler({})
        errors = []
        handler._send = lambda status, payload: errors.append((status, payload))
        assert http_server.Handler._reject_identity_fields(handler, candidate) is False
        assert errors[0][0] == 400

    for candidate in (
        {"tenant": "retired-value"},
        {"record": {"tenant": "retired-value"}},
        {"provenance": {"tenant": "retired-value"}},
        {"record": {"provenance": {"tenant": "retired-value"}}},
    ):
        handler = _handler({})
        errors = []
        handler._send = lambda status, payload: errors.append((status, payload))
        assert http_server.Handler._reject_identity_fields(handler, candidate) is False
        assert errors[0][0] == 400


def test_root_scope_fails_closed_for_missing_nonexistent_and_symlink_roots(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(allowed)],
        }
    }))
    for requested in ("", str(tmp_path / "missing")):
        handler = _handler({})
        errors = []
        handler._send = lambda status, payload: errors.append((status, payload))
        assert http_server.Handler._bind_root(handler, requested) is None
        assert errors[0][0] == 400

    link = tmp_path / "allowed-link"
    try:
        link.symlink_to(allowed, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this host")
    handler = _handler({})
    errors = []
    handler._send = lambda status, payload: errors.append((status, payload))
    assert http_server.Handler._bind_root(handler, str(link)) is None
    assert errors[0][0] == 400

    http_server.APP.config["security"]["allowed_roots"] = []
    handler = _handler({})
    errors = []
    handler._send = lambda status, payload: errors.append((status, payload))
    assert http_server.Handler._bind_root(handler, str(allowed)) is None
    assert errors[0][0] == 403

    scoped_task_handler = _handler({})
    scoped_task_errors = []
    scoped_task_handler._send = lambda status, payload: scoped_task_errors.append((status, payload))
    assert http_server.Handler._bind_task_payload(scoped_task_handler, {
        "root": str(tmp_path / "missing-task-root"), "task_id": "task-a",
    }) is False
    assert scoped_task_errors[0][0] == 400


def test_api_token_authorizes_owner_without_root_identity_rewrite(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {
            "api_token": "owner-token-long",
            "api_token_permissions": ["read", "write"],
            "allowed_roots": [str(tmp_path)],
        }
    }))
    handler = _handler({
        "X-LocalAI-Token": "owner-token-long",
    })
    assert http_server.Handler._authorized(handler, "read") is True
    assert handler._authorization_actor == "api_token"
    assert handler._authorization_permissions == frozenset({"read", "write"})

    scoped = _handler({})
    assert http_server.Handler._bind_root(scoped, str(root)) == str(root.resolve())
    assert scoped._authorization_root == str(root.resolve())


def test_global_memory_stays_owner_global_and_session_scope_is_explicit(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "security": {"api_token": "owner-token-long"}
    }))
    handler = _handler({})
    payload = {"scope": "global", "key": "private"}
    assert http_server.Handler._bind_memory_payload(handler, payload) is True
    assert payload == {"scope": "global", "key": "private"}

    query = {"scope": ["global"]}
    query_handler = _handler({})
    assert http_server.Handler._bind_memory_query(query_handler, query) is True
    assert query == {"scope": ["global"]}

    session = {"scope": "session", "session_id": "session-actual", "scope_id": "session-actual"}
    assert http_server.Handler._bind_memory_payload(_handler({}), session) is True
    assert session["session_id"] == session["scope_id"] == "session-actual"

    denied = _handler({})
    responses = []
    denied._send = lambda status, data: responses.append((status, data))
    assert http_server.Handler._bind_memory_payload(denied, {"scope": "task", "task_id": "secret-task"}) is False
    assert responses[0][0] == 400


def test_debug_trace_request_keeps_complete_paths_and_ordinary_context(tmp_path):
    raw_root = str(tmp_path / "sensitive-project")
    captured = http_server.Handler._safe_debug_trace_request({
        "root": raw_root,
        "target_root": raw_root,
        "context": {"repo_root": raw_root, "repository_id": raw_root},
    })
    serialized = json.dumps(captured)
    assert json.dumps(raw_root, ensure_ascii=False)[1:-1] in serialized
    assert raw_root in captured["context"]["repo_root"]
    assert captured["root"] == raw_root
    assert captured["target_root"] == raw_root
    assert captured["context"]["repo_root"] == raw_root
    assert captured["context"]["repository_id"] == raw_root
    assert "tenant" not in captured


def test_agent_state_event_endpoints_fail_closed_without_scoping(monkeypatch):
    event_calls = []
    app = SimpleNamespace(agent_state=SimpleNamespace(
        enabled=True,
        events=lambda **kwargs: event_calls.append(kwargs) or [],
    ))
    events = _dispatch_get(monkeypatch, "/api/agent-state/events", app)
    stream = _dispatch_get(monkeypatch, "/api/agent-state/events/stream", app)

    assert events[0][0] == 400
    assert stream[0][0] == 400
    assert event_calls == []


def test_agent_state_status_does_not_return_global_task_ids(monkeypatch):
    app = SimpleNamespace(agent_tasks=SimpleNamespace(
        list_tasks=lambda: [SimpleNamespace(task_id="foreign-task", status=http_server.TaskStatus.ACTIVE)],
    ))

    responses = _dispatch_get(monkeypatch, "/api/status?detail=agent_state", app)

    assert responses[0][0] == 200
    assert responses[0][1]["active_tasks"] == []
    assert responses[0][1]["tasks_count"] == 0
    assert "foreign-task" not in json.dumps(responses[0][1])


def test_memory_task_query_requires_existing_task_in_bound_root(tmp_path, monkeypatch):
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    agent_state, coordination_id = _project_state(root_a, tmp_path / "state")
    task = SimpleNamespace(task_id="known-task", context=SimpleNamespace(
        repository_id=coordination_id, session_id="session-root-a",
    ), checkpoint=SimpleNamespace(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(root_a.resolve())},
    }))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(tmp_path)],
        }},
        agent_state=agent_state,
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
    agent_state, coordination_id = _project_state(root_a, tmp_path / "state")
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=coordination_id, session_id="session-root-a",
    ), checkpoint=SimpleNamespace(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(root_a.resolve())},
    }))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "allowed_roots": [str(tmp_path)],
    }}, agent_state=agent_state,
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None)))

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
    agent_state, coordination_id = _project_state(root_a, tmp_path / "state")
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=coordination_id, session_id="session-root-a",
    ), checkpoint=SimpleNamespace(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(root_a.resolve())},
    }))
    calls = []
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(tmp_path)],
        }},
        agent_state=agent_state,
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
def test_workspace_memory_actions_bind_to_explicit_root(tmp_path, monkeypatch, path):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "allowed_roots": [str(root)],
    }}))
    handler = _handler({})
    responses = []
    handler._send = lambda status, payload: responses.append((status, payload))

    assert http_server.Handler._bind_workspace_memory_payload(
        handler, path, {"root": str(root), "query": "private", "key": "k", "value": "v"}
    ) is True
    assert handler._authorization_root == str(root.resolve())

    delete_handler = _handler({})
    assert http_server.Handler._bind_workspace_memory_payload(
        delete_handler, "/api/memory/delete", {"root": str(root), "key": "k"}
    ) is True
    assert delete_handler._authorization_root == str(root.resolve())

    denied_root = _handler({})
    root_responses = []
    denied_root._send = lambda status, payload: root_responses.append((status, payload))
    assert http_server.Handler._bind_workspace_memory_payload(
        denied_root, "/api/memory/put", {"root": str(tmp_path), "key": "k", "value": "v"}
    ) is False
    assert root_responses[0][0] == 403


def test_debug_trace_captures_prompt_source_and_complete_project_path():
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
    assert "private source body" in serialized
    assert "private prompt text" in serialized
    assert "private query" in serialized
    assert "private transcript" in serialized
    assert "private code" in serialized
    assert "C:/private/repository" in serialized
    assert captured["context"]["repository_id"] == "C:/private/repository"


@pytest.mark.parametrize(("action", "expected_status"), [
    ("reap", 400), ("reap_expired", 200), ("zombie_reap", 400), ("recover_zombie_tasks", 400),
])
def test_task_reaper_canonical_action_is_scoped_and_retired_aliases_reject(tmp_path, monkeypatch, action, expected_status):
    root = tmp_path / "allowed"
    root.mkdir()
    state, coordination_id = _project_state(root, tmp_path / "state")
    calls = []
    canonical_root = str(root.resolve())
    task = SimpleNamespace(
        context=SimpleNamespace(repository_id=coordination_id, session_id="session-actual"),
        checkpoint=SimpleNamespace(state_data={
            "_agent_task_scope": {"version": 2, "repo_root": canonical_root},
        }),
    )
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(root)],
        }},
        agent_state=state,
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            get=lambda task_id: task if task_id == "task-1" else None,
            reap_expired_heartbeats=lambda now=None, *, auto_recover=False, repo_root=None, task_id=None: calls.append((
                "reap", {"auto_recover": auto_recover, "repo_root": repo_root, "task_id": task_id}
            )) or ["task-1"],
            recover_zombie_tasks=lambda now=None, *, repo_root=None, task_id=None: calls.append((
                "recover", {"repo_root": repo_root, "task_id": task_id}
            )) or ["task-1"],
        ),
    )
    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        {
            "root": str(root),
            "action": action,
            "task_id": "task-1",
            "auto_recover": True,
        },
        app,
        headers={"X-LocalAI-Token": "a-long-test-token-value"},
        authenticate=True,
    )

    assert responses[0][0] == expected_status
    if expected_status == 400:
        assert responses[0][1]["success"] is False
        assert calls == []
    else:
        assert responses[0][1]["reaped"] == ["task-1"]
        assert calls == [("reap", {
            "auto_recover": True,
            "repo_root": canonical_root,
            "task_id": "task-1",
        })]


def test_task_reaper_uses_authenticated_token_and_explicit_repository_root(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    state, coordination_id = _project_state(root, tmp_path / "state")
    calls = []
    canonical_root = str(root.resolve())
    task = SimpleNamespace(
        context=SimpleNamespace(repository_id=coordination_id, session_id="session-real-task"),
        checkpoint=SimpleNamespace(state_data={
            "_agent_task_scope": {"version": 2, "repo_root": canonical_root},
        }),
    )
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(root)],
        }},
        agent_state=state,
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            get=lambda task_id: task if task_id == "task-1" else None,
            reap_expired_heartbeats=lambda **kwargs: calls.append(kwargs) or ["task-1"],
        ),
    )
    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        {"root": str(root), "action": "reap_expired", "task_id": "task-1"},
        app,
        headers={"X-LocalAI-Token": "a-long-test-token-value"},
        authenticate=True,
    )

    assert responses[0][0] == 200
    assert calls[0]["repo_root"] == canonical_root


@pytest.fixture
def scoped_reaper_store(tmp_path, monkeypatch):
    from local_ai_hub import trace_context
    from local_ai_hub.agent_events import AgentStateStore
    from local_ai_hub.agent_identity import ScopeContext
    from local_ai_hub.agent_tasks import GoalContract, TaskStatus, TaskStore

    root, other_root = tmp_path / "allowed", tmp_path / "other"
    root.mkdir()
    other_root.mkdir()
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    from local_ai_hub.project_config import resolve_project_context

    coordination_id = resolve_project_context(root, tmp_path).coordination_id
    store = TaskStore(state_store)

    def create(task_id, task_root, session_id):
        token = trace_context.set_context(agent="trace-agent", request_id="trace-request")
        try:
            store.create(GoalContract(goal="Recover scoped expired work"), ScopeContext(
                repository_id=coordination_id, session_id=session_id, task_id=task_id,
            ), task_id=task_id, repo_root=str(task_root), actor="owner")
            store.transition(task_id, TaskStatus.ACTIVE, reason="start", actor="owner", idempotency_key=f"start-{task_id}")
        finally:
            trace_context.reset_context(token)

    old_time = time.time() - 1000
    with monkeypatch.context() as clock:
        clock.setattr("local_ai_hub.agent_tasks.time.time", lambda: old_time)
        create("target", root, "session-target")
        create("sibling", root, "session-sibling")
        create("other-root", other_root, "session-other-root")
        create("different-session", root, "session-distinct")
    create("fresh", root, "session-fresh")
    app = SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value", "allowed_roots": [str(root)],
    }}, agent_state=state_store, agent_tasks=store, recovery=None)
    headers = {"X-LocalAI-Token": "a-long-test-token-value"}

    def post(task_id, **extra):
        return _dispatch_post(monkeypatch, "/api/agent-state/tasks", {
            "action": "reap_expired", "root": str(root), "task_id": task_id, **extra,
        }, app, headers=headers, authenticate=True)[0]

    return store, post


@pytest.mark.parametrize("auto_recover", [False, True])
def test_scoped_reaper_real_store_preserves_other_tasks_and_identities(scoped_reaper_store, auto_recover):
    from local_ai_hub.agent_tasks import TaskStatus
    store, post = scoped_reaper_store
    before = {name: store.get(name) for name in ("sibling", "other-root", "different-session", "fresh")}
    status, result = post("target", auto_recover=auto_recover)
    assert status == 200 and result["reaped"] == ["target"]
    assert store.get("target").status is (TaskStatus.WAITING if auto_recover else TaskStatus.ABANDONED)
    assert {name: store.get(name) for name in before} == before


@pytest.mark.parametrize("task_id", ["other-root", "missing"])
def test_scoped_reaper_hides_foreign_or_missing_tasks(scoped_reaper_store, task_id):
    store, post = scoped_reaper_store
    before = {name: store.get(name) for name in ("target", "sibling", "other-root", "different-session", "fresh")}
    status, result = post(task_id, auto_recover=True)
    assert status == 404 and result["success"] is False
    assert {name: store.get(name) for name in before} == before


def test_scoped_reaper_does_not_partition_tasks_by_session(scoped_reaper_store):
    store, post = scoped_reaper_store
    status, result = post("different-session", auto_recover=True)
    assert status == 200 and result["reaped"] == ["different-session"]
    assert store.get("different-session").context.session_id == "session-distinct"


@pytest.mark.parametrize(("task_id", "auto_recover"), [
    ("", True), (None, True), (3, True), (True, True), (" target ", True),
    ("target", "true"), ("target", 1), ("target", None),
])
def test_scoped_reaper_rejects_invalid_mutation_inputs(scoped_reaper_store, task_id, auto_recover):
    store, post = scoped_reaper_store
    before = store.get("target")
    status, result = post(task_id, auto_recover=auto_recover)
    assert status == 400 and result["success"] is False
    assert store.get("target") == before


def test_scoped_reaper_preserves_fresh_task(scoped_reaper_store):
    store, post = scoped_reaper_store
    before = store.get("fresh")
    status, result = post("fresh", auto_recover=True)
    assert status == 200 and result["reaped"] == []
    assert store.get("fresh") == before


def test_scoped_reaper_does_not_overwrite_concurrent_heartbeat(scoped_reaper_store, monkeypatch):
    from local_ai_hub.agent_tasks import TaskStatus
    store, post = scoped_reaper_store
    transition = store.transition
    renewed = []

    def renew_before_transition(task_id, target, **kwargs):
        renewed.append(store.heartbeat(task_id, actor="owner"))
        return transition(task_id, target, **kwargs)

    monkeypatch.setattr(store, "transition", renew_before_transition)
    status, result = post("target", auto_recover=True)
    assert status == 200 and result["reaped"] == []
    assert len(renewed) == 1
    assert store.get("target") == renewed[0]
    assert store.get("target").status is TaskStatus.ACTIVE
    assert store.get("target").heartbeat_expires_at > time.time()


def test_scoped_reaper_does_not_report_store_failure_as_empty_success(scoped_reaper_store, monkeypatch):
    store, _ = scoped_reaper_store
    before = store.get("target")

    def fail_transition(*args, **kwargs):
        raise RuntimeError("transition persistence unavailable")

    monkeypatch.setattr(store, "transition", fail_transition)
    with pytest.raises(RuntimeError, match="transition persistence unavailable"):
        store.reap_expired_heartbeats(
            repo_root=before.context.repository_id, task_id="target",
        )
    assert store.get("target") == before


def test_task_list_accepts_authenticated_token_and_explicit_root(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
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
        headers={"X-LocalAI-Token": "a-long-test-token-value"},
        authenticate=True,
    )

    assert responses[0][0] == 200
    assert responses[0][1]["tasks"] == []


def test_root_memory_preserves_global_scope_with_authenticated_owner_token(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "allowed_roots": [str(root)],
    }}))
    handler = _handler({"X-LocalAI-Token": "a-long-test-token-value"})
    errors = []
    handler._send = lambda status, response: errors.append((status, response))
    payload = {"root": str(root), "scope": "global"}
    handler.headers["X-LocalAI-Token"] = "a-long-test-token-value"
    assert http_server.Handler._authorized(handler, "write") is True

    assert http_server.Handler._bind_memory_payload(handler, payload) is True
    assert errors == []
    assert payload == {"root": str(root.resolve()), "scope": "global"}


def test_root_session_memory_requires_explicit_matching_session(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "allowed_roots": [str(root)],
    }}))
    handler = _handler({"X-LocalAI-Token": "a-long-test-token-value"})
    responses = []
    handler._send = lambda status, response: responses.append((status, response))
    payload = {"root": str(root), "scope": "session", "session_id": "session-actual"}

    assert http_server.Handler._authorized(handler, "write") is True
    assert http_server.Handler._bind_memory_payload(handler, payload) is True
    assert responses == []
    assert payload["root"] == str(root.resolve())
    assert payload["session_id"] == "session-actual"


@pytest.mark.parametrize(("action", "expected_status"), [
    ("curate_dataset", 200),
    ("curate_training_dataset", 400),
])
def test_task_dataset_curation_forwards_authenticated_root_scope(tmp_path, monkeypatch, action, expected_status):
    root = tmp_path / "allowed"
    root.mkdir()
    state, _coordination_id = _project_state(root, tmp_path / "state")
    calls = []

    def curate_training_dataset(
        output_path,
        min_receipts=1,
        format="jsonl",
        *,
        repo_root=None,
        task_id=None,
    ):
        calls.append(((output_path,), {
            "min_receipts": min_receipts,
            "format": format,
            "repo_root": repo_root,
            "task_id": task_id,
        }))
        return {"success": True}

    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(root)],
        }},
        agent_state=state,
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            curate_training_dataset=curate_training_dataset,
        ),
    )
    canonical_root = str(root.resolve())

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
        headers={"X-LocalAI-Token": "a-long-test-token-value"},
    )

    assert responses[0][0] == expected_status
    if expected_status != 200:
        assert responses[0][1]["success"] is False
        assert calls == []
        return
    assert responses[0][1]["success"] is True
    assert calls == [(("dataset.jsonl",), {
        "min_receipts": 3,
        "format": "jsonl",
        "repo_root": canonical_root,
        "task_id": "task-1",
    })]


@pytest.mark.parametrize("payload,headers", [
    ({"action": "reap"}, {}),
    ({"action": "curate_dataset", "root": "C:/outside"}, {}),
    ({"action": "reap_expired", "root": "{root}"}, {"X-LocalAI-Tenant": "header-retired"}),
])
def test_scoped_task_operations_reject_invalid_root_or_retired_header_before_store_mutation(
    tmp_path, monkeypatch, payload, headers
):
    root = tmp_path / "allowed"
    root.mkdir()
    calls = []
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
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

    expected_status = 400
    assert responses[0][0] == expected_status
    assert calls == []


@pytest.mark.parametrize("case", ["wrong_token", "retired_header", "retired_body"])
def test_scoped_task_routes_fail_closed_on_authentication_or_retired_identity(
    tmp_path, monkeypatch, case
):
    root = tmp_path / "allowed"
    root.mkdir()
    security = {
        "api_token": "a-long-test-token-value",
        "allowed_roots": [str(root)],
    }
    app = SimpleNamespace(
        config={"security": security},
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            reap_expired_heartbeats=lambda **_kwargs: pytest.fail("scope mismatch reached task store"),
        ),
    )
    headers = {
        "X-LocalAI-Token": "wrong-token" if case == "wrong_token" else security["api_token"],
    }
    if case == "retired_header":
        headers["X-LocalAI-Tenant"] = ""
    payload = {"root": str(root), "action": "reap_expired"}
    if case == "retired_body":
        payload["tenant"] = None

    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/tasks",
        payload,
        app,
        headers=headers,
        authenticate=True,
    )

    expected_status = {"wrong_token": 401, "retired_header": 400, "retired_body": 400}[case]
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
        config={},
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
        config={},
        agent_state=spy,
        agent_blackboard=spy,
        swarm=spy,
        agent_tasks=spy,
        agent_incidents=spy,
        agent_learning=spy,
        agent_context=spy,
    )

    responses = _dispatch_post(monkeypatch, path, {"action": action}, app)

    retired_blackboard_actions = {
        "put", "blackboard_update", "read", "blackboard_get",
        "blackboard_list", "blackboard_merge", "remove", "blackboard_delete",
    }
    expected_status = 400 if path == "/api/agent-state/blackboard" and action in retired_blackboard_actions else 403
    assert responses[0][0] == expected_status
    assert responses[0][1]["success"] is False
    assert calls == []


@pytest.mark.parametrize(("path", "expected_status"), [
    ("/api/code/ast_rename", 400),
    ("/api/ast_rename", 404),
    ("/api/code/batch_replace", 400),
    ("/api/repo/batch_replace", 404),
])
def test_unscoped_file_mutation_routes_deny_before_service_access(monkeypatch, path, expected_status):
    calls = []
    services = SimpleNamespace(
        ast_rename=lambda *args, **kwargs: calls.append((args, kwargs)),
        batch_replace=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    app = SimpleNamespace(
        config={"security": {"api_token": "mutation-token-long"}},
        services=services,
        deterministic=SimpleNamespace(),
        recovery=None,
    )
    responses = _dispatch_post(monkeypatch, path, {"root": ""}, app)

    assert responses[0][0] == expected_status
    assert responses[0][1]["success"] is False
    assert calls == []


@pytest.mark.parametrize("path", [
    "/api/git/status",
    "/api/repo/dead_code",
    "/api/code/find_symbol",
    "/api/worktrees",
    "/api/preprocess/status",
])
def test_unscoped_repository_get_routes_deny_before_service_access(monkeypatch, path):
    calls = []
    app = SimpleNamespace(
        config={"security": {"api_token": "repo-token-long"}},
        services=SimpleNamespace(
            git_status=lambda *args, **kwargs: calls.append((args, kwargs)),
            dead_code=lambda *args, **kwargs: calls.append((args, kwargs)),
            code_find_symbol=lambda *args, **kwargs: calls.append((args, kwargs)),
        ),
        deterministic=SimpleNamespace(),
        recovery=None,
    )

    responses = _dispatch_get(monkeypatch, path, app)

    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "root_required"
    assert calls == []


def test_repository_get_rejects_retired_tenant_query_field(monkeypatch, tmp_path):
    calls = []
    app = SimpleNamespace(
        config={"security": {}},
        services=SimpleNamespace(dead_code=lambda *args, **kwargs: calls.append((args, kwargs))),
        deterministic=SimpleNamespace(),
        recovery=None,
    )
    path = f"/api/dead_code?root={tmp_path}&tenant="
    responses = _dispatch_get(monkeypatch, path, app)

    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "retired_tenancy_field"
    assert calls == []


def test_logs_tail_does_not_disclose_state_path(monkeypatch, tmp_path):
    app = SimpleNamespace(
        config={"server": {"state_dir": str(tmp_path)}},
        recovery=None,
    )
    responses = _dispatch_get(monkeypatch, "/api/logs/tail?lines=10", app)

    assert responses[0][0] == 200
    assert "path" not in responses[0][1]
    assert str(tmp_path) not in str(responses[0][1])


def test_get_internal_error_does_not_disclose_exception(monkeypatch):
    log_calls = []
    app = SimpleNamespace(
        config={"security": {}},
        services=SimpleNamespace(run_doctor=lambda: (_ for _ in ()).throw(RuntimeError("private traceback payload"))),
        logger=SimpleNamespace(error=lambda *args, **kwargs: log_calls.append((args, kwargs))),
        recovery=None,
    )
    responses = _dispatch_get(monkeypatch, "/api/doctor", app)

    assert responses[0][0] == 500
    assert responses[0][1]["error_code"] == "internal_error"
    assert "private traceback payload" not in str(responses[0][1])
    assert "private traceback payload" not in str(log_calls)
    assert log_calls[0][0] == ("GET request failed error_type=%s", "RuntimeError")
    assert "/api/doctor" not in str(log_calls)


def test_post_internal_error_does_not_disclose_exception(monkeypatch):
    log_calls = []
    app = SimpleNamespace(
        config={"security": {}},
        services=SimpleNamespace(run_doctor=lambda: (_ for _ in ()).throw(RuntimeError("private post payload"))),
        logger=SimpleNamespace(error=lambda *args, **kwargs: log_calls.append((args, kwargs))),
        recovery=None,
    )
    responses = _dispatch_post(monkeypatch, "/api/doctor", {}, app)

    assert responses[0][0] == 500
    assert responses[0][1]["error_code"] == "internal_error"
    assert "private post payload" not in str(responses[0][1])
    assert "private post payload" not in str(log_calls)
    assert log_calls[0][0] == ("POST request failed error_type=%s", "RuntimeError")
    assert "/api/doctor" not in str(log_calls)


def test_config_route_exposes_file_labels_without_host_paths(monkeypatch, tmp_path):
    config_path = tmp_path / "private" / "hub.toml"
    override_path = tmp_path / "private" / "runtime-overrides.toml"
    app = SimpleNamespace(
        config={
            "security": {"api_token": "secret-token"},
            "_config_path": str(config_path),
            "_runtime_override_path": str(override_path),
        },
        recovery=None,
    )
    responses = _dispatch_get(monkeypatch, "/api/config", app)

    assert responses[0][0] == 200
    payload = responses[0][1]
    assert payload["config"]["security"]["api_token"] == "***configured***"
    assert payload["config_path"] == "hub.toml"
    assert payload["runtime_override_path"] == "runtime-overrides.toml"
    assert str(tmp_path) not in str(payload)


def test_config_update_reset_exposes_file_label_without_host_path(monkeypatch, tmp_path):
    app = SimpleNamespace(
        config={
            "security": {},
            "features": {"dashboard": True},
            "_config_path": str(tmp_path / "hub.toml"),
        },
        recovery=None,
    )
    override_path = tmp_path / "private" / "runtime-overrides.toml"
    monkeypatch.setattr(http_server, "save_runtime_overrides", lambda *args, **kwargs: override_path)
    responses = _dispatch_post(monkeypatch, "/api/config/update", {"action": "reset"}, app)

    assert responses[0][0] == 200
    assert responses[0][1]["runtime_override_path"] == "runtime-overrides.toml"
    assert str(tmp_path) not in str(responses[0][1])


def test_config_update_error_does_not_disclose_host_path(monkeypatch, tmp_path):
    log_calls = []
    app = SimpleNamespace(
        config={"security": {}, "_config_path": str(tmp_path / "hub.toml")},
        logger=SimpleNamespace(error=lambda *args, **kwargs: log_calls.append((args, kwargs))),
        recovery=None,
    )
    private_path = str(tmp_path / "private" / "runtime-overrides.toml")

    def fail_write(*args, **kwargs):
        raise OSError(f"permission denied: {private_path}")

    monkeypatch.setattr(http_server, "save_runtime_overrides", fail_write)
    responses = _dispatch_post(
        monkeypatch,
        "/api/config/update",
        {"settings": {"features.dashboard": False}},
        app,
    )

    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "config_update_rejected"
    assert responses[0][1]["error"] == "configuration update rejected"
    assert private_path not in str(responses[0][1])
    assert private_path not in str(log_calls)
    assert log_calls[0][0] == ("config update rejected error_type=%s", "OSError")


@pytest.mark.parametrize(("path", "expected_status"), [
    ("/api/git/status", 400),
    ("/api/repo/state", 400),
    ("/api/code/find_symbol", 400),
    ("/api/code-intelligence/query", 400),
    ("/api/reachability_dead_code", 404),
    ("/api/callers", 404),
])
def test_unscoped_repository_routes_deny_before_service_access(monkeypatch, path, expected_status):
    calls = []
    services = SimpleNamespace(
        git_status=lambda *args, **kwargs: calls.append((args, kwargs)),
        code_find_symbol=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    app = SimpleNamespace(
        config={"security": {"api_token": "repo-token-long"}},
        services=services,
        deterministic=SimpleNamespace(),
        external_tools=SimpleNamespace(query=lambda *args, **kwargs: calls.append((args, kwargs))),
        recovery=None,
    )
    responses = _dispatch_post(monkeypatch, path, {}, app)

    assert responses[0][0] == expected_status
    assert calls == []


@pytest.mark.parametrize(("path", "expected_status"), [
    ("/api/repo/cross_repo_contract", 400),
    ("/api/cross_repo_contract", 404),
    ("/api/cross_project_graph", 400),
    ("/api/cross_project_symbols", 400),
    ("/api/cross_project_impact", 400),
])
def test_cross_repository_routes_require_explicit_roots(monkeypatch, path, expected_status):
    calls = []
    app = SimpleNamespace(
        config={"security": {"api_token": "cross-repo-token-long"}},
        services=SimpleNamespace(cross_repo_contract=lambda *args, **kwargs: calls.append(args)),
        deterministic=SimpleNamespace(cross_project_graph=lambda *args: calls.append(args)),
        preprocessor=SimpleNamespace(status=lambda: {"projects": [{"root": "C:/untrusted"}]}),
        recovery=None,
    )
    responses = _dispatch_post(monkeypatch, path, {}, app)

    assert responses[0][0] == expected_status
    assert responses[0][1]["success"] is False
    assert calls == []


def test_cross_project_graph_get_requires_explicit_roots(monkeypatch):
    calls = []
    app = SimpleNamespace(
        config={"security": {"api_token": "cross-repo-token-long"}},
        deterministic=SimpleNamespace(cross_project_graph=lambda *args: calls.append(args)),
        preprocessor=SimpleNamespace(status=lambda: (_ for _ in ()).throw(AssertionError("global fallback"))),
        recovery=None,
    )
    responses = _dispatch_get(monkeypatch, "/api/cross_project_graph", app)

    assert responses[0][0] == 400
    assert responses[0][1]["error_code"] == "roots_required"
    assert calls == []


def test_cross_project_graph_get_forwards_bound_roots(monkeypatch):
    calls = []
    app = SimpleNamespace(
        config={"security": {"api_token": "cross-repo-token-long"}},
        deterministic=SimpleNamespace(
            cross_project_graph=lambda roots: calls.append(roots) or {"success": True}
        ),
        recovery=None,
    )

    def bind_root(_handler, root):
        canonical = str(root).replace("\\", "/").rstrip("/")
        _handler._authorization_root = canonical
        return canonical

    monkeypatch.setattr(http_server.Handler, "_bind_root", bind_root)
    responses = _dispatch_get(
        monkeypatch,
        "/api/cross_project_graph?roots=C:/frontend&roots=C:/backend",
        app,
    )

    assert responses[0][0] == 200
    assert calls == [["C:/frontend", "C:/backend"]]


def test_cross_project_impact_rejects_origin_outside_explicit_roots(monkeypatch):
    calls = []
    app = SimpleNamespace(
        config={"security": {"api_token": "cross-repo-token-long"}},
        deterministic=SimpleNamespace(cross_project_impact=lambda *args, **kwargs: calls.append(args)),
        recovery=None,
    )
    def bind_root(_handler, root):
        canonical = str(root).replace("\\", "/")
        _handler._authorization_root = canonical
        return canonical

    monkeypatch.setattr(http_server.Handler, "_bind_root", bind_root)
    responses = _dispatch_post(
        monkeypatch,
        "/api/cross_project_impact",
        {"roots": ["C:/backend", "C:/frontend"], "origin_root": "C:/untrusted", "symbol": "Api"},
        app,
    )

    assert responses[0][0] == 400
    assert calls == []


def test_authenticated_learning_route_dispatches_candidate_mutation(monkeypatch):
    token = "learning-token-long"
    saved = []
    learning = SimpleNamespace(
        state_store=SimpleNamespace(enabled=True),
        create_candidate=lambda candidate: saved.append(candidate) or candidate,
    )
    app = SimpleNamespace(
        config={
            "security": {
                "api_token": token,
                "api_token_permissions": ["write"],
            }
        },
        agent_learning=learning,
        recovery=None,
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/learning",
        {
            "action": "create_candidate",
            "candidate": {
                "name": "bounded-candidate",
                "baseline_version": "base",
                "candidate_version": "next",
            },
        },
        app,
        headers={"X-LocalAI-Token": token},
        authenticate=True,
    )

    assert responses[0][0] == 200
    assert len(saved) == 1
    assert saved[0].name == "bounded-candidate"


def test_authenticated_incident_find_requires_and_forwards_root_scope(monkeypatch, tmp_path):
    token = "incident-token-long"
    calls = []
    incidents = SimpleNamespace(
        state_store=SimpleNamespace(enabled=True),
        find_negative_knowledge=lambda query, limit, *, root: calls.append(
            (query, limit, root)
        ) or [],
    )
    app = SimpleNamespace(
        config={
            "security": {
                "api_token": token,
                "api_token_permissions": ["write"],
                "allowed_roots": [str(tmp_path)],
            }
        },
        agent_incidents=incidents,
        recovery=None,
    )
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *_args, **_kwargs: None)
    responses = _dispatch_post(
        monkeypatch,
        "/api/agent-state/incidents",
        {"action": "find", "query": "TimeoutError", "root": str(tmp_path)},
        app,
        headers={"X-LocalAI-Token": token},
        authenticate=True,
    )

    assert responses[0][0] == 200
    assert calls and calls[0][0] == "TimeoutError"
    assert calls[0] == ("TimeoutError", 100, str(tmp_path.resolve()))


def test_debug_trace_keeps_user_facing_error_but_not_internal_exception_text(monkeypatch):
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
    assert "private response exception text" in stored
    assert "private traceback and source prompt" not in stored
    assert "traceback" not in stored.lower()


def test_context_compile_binds_existing_task_root_without_changing_task_id_contract(tmp_path, monkeypatch):
    from local_ai_hub.task_context import build_context_request

    root = tmp_path / "repo"
    root.mkdir()
    agent_state, coordination_id = _project_state(root, tmp_path / "state")
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=coordination_id, session_id="session-context-real",
    ), checkpoint=SimpleNamespace(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(root.resolve())},
    }))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "allowed_roots": [str(root)],
    }}, agent_state=agent_state,
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None)))
    handler = _handler({"X-LocalAI-Token": "a-long-test-token-value"})
    payload = {"action": "compile", "task_id": "task-a"}

    assert http_server.Handler._bind_context_payload(handler, payload) is True
    request = build_context_request(payload)
    assert request.task_id == "task-a"
    assert request.root == str(root.resolve())
    assert request.session_id == "session-context-real"
    assert request.scoped_task_only is True


def test_context_compile_rejects_foreign_or_unknown_task_before_compile(tmp_path, monkeypatch):
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    agent_state, coordination_id = _project_state(root_a, tmp_path / "state")
    task_a = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=coordination_id, session_id="session-a",
    ), checkpoint=SimpleNamespace(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(root_a.resolve())},
    }))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "allowed_roots": [str(tmp_path)],
    }}, agent_state=agent_state,
        agent_tasks=SimpleNamespace(get=lambda task_id: task_a if task_id == "task-a" else None)))

    for payload in ({"task_id": "missing"}, {"task_id": "task-a", "root": str(root_b)}):
        handler = _handler({})
        responses = []
        handler._send = lambda status, value: responses.append((status, value))
        assert http_server.Handler._bind_context_payload(handler, payload) is False
        assert responses[0][0] in {403, 404}


def test_task_event_reads_allow_only_owned_task_stream(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    agent_state, coordination_id = _project_state(root, tmp_path / "state")
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=coordination_id, session_id="session-events-real",
    ), checkpoint=SimpleNamespace(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(root.resolve())},
    }))
    calls = []
    app = SimpleNamespace(
        config={"security": {
            "api_token": "a-long-test-token-value",
            "allowed_roots": [str(root)],
        }},
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None),
        agent_state=SimpleNamespace(
            enabled=True,
            db_path=agent_state.db_path,
            events=lambda **kwargs: calls.append(kwargs) or [],
        ),
    )
    handler = _handler({"X-LocalAI-Token": "a-long-test-token-value"}, path=(
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
    agent_state, coordination_id = _project_state(root, tmp_path / "state")
    task = SimpleNamespace(task_id="task-a", context=SimpleNamespace(
        repository_id=coordination_id, session_id="session-board-real",
    ), checkpoint=SimpleNamespace(state_data={
        "_agent_task_scope": {"version": 2, "repo_root": str(root.resolve())},
    }))
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={"security": {
        "api_token": "a-long-test-token-value",
        "allowed_roots": [str(root)],
    }}, agent_state=agent_state,
        agent_tasks=SimpleNamespace(get=lambda task_id: task if task_id == "task-a" else None)))

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
    monkeypatch.setattr(config_module, "load_config", lambda *_args, **_kwargs: {
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
            '[security]\napi_token = "long-secure-token-value-12345"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="server.bind must be 127.0.0.1"):
            load_config(str(config))

    config.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\nbind = "127.0.0.1"\n'
        '[security]\nallow_remote = false\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="security.allow_remote was removed"):
        load_config(str(config))

    config.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\nbind = "127.0.0.1"\n'
        'client_host = "remote.example"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="server.client_host was removed"):
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
    # This fixture tests direct OS parent semantics, not venv launcher behavior.
    base_executable = Path(sys._base_executable).resolve()
    assert base_executable.is_file()
    import sysconfig
    env["PYTHONPATH"] += os.pathsep + sysconfig.get_path("purelib")
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
    wrapper = process_utils.popen_managed(
        [str(base_executable), "-c", wrapper_code], cwd=source_root, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **process_utils.hidden_run_kwargs(text=True),
    )
    try:
        wrapper_stdout, wrapper_stderr = wrapper.communicate(timeout=10)
    finally:
        assert process_utils.terminate_tree(wrapper.pid, process_handle=wrapper)
        wrapper.wait(timeout=2)
    assert wrapper.returncode == 0, wrapper_stderr
    wrapper_pid, child_pid, child_parent_pid, snapshot_parent = (
        int(value) for value in wrapper_stdout.strip().split("\t")
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


def test_async_job_trace_persists_complete_input_and_output_when_enabled(tmp_path, monkeypatch):
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
        def put(self, _content, *, kind):
            return "artifact-1"

    manager = AsyncJobManager(
        config,
        scheduler=object(),
        artifacts=Artifacts(),
        executor=lambda _action, _payload: {
            "success": True,
            "answer": "ordinary response text",
            "api_key": "api-secret",
        },
        debug_traces=traces,
    )
    try:
        submitted = manager.submit(
            "reason",
            {"task": "private prompt text", "context": "private source text"},
        )
        assert manager.wait(submitted["job_id"], 3)["state"] == "done"
        detail = traces.detail(submitted["trace_id"], full_payload=True)
        serialized = json.dumps(detail, ensure_ascii=False)

        assert "private prompt text" in serialized
        assert "private source text" in serialized
        assert "ordinary response text" in serialized
        assert "api-secret" in serialized
    finally:
        manager.close()
