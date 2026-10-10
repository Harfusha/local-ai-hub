from __future__ import annotations

from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from local_ai_hub import supervisor as module


@pytest.fixture
def supervisor_probe(monkeypatch, tmp_path):
    instance = object.__new__(module.Supervisor)
    instance.config = {"server": {"bind": "127.0.0.1", "port": 11435}, "security": {}}
    instance.cfg = {}
    instance.state_dir = tmp_path
    instance.child = SimpleNamespace(pid=10, poll=lambda: None)
    instance.child_ready = True
    instance.child_owner = {"pid": 10}
    monkeypatch.setattr(instance, "_owned_hub_child", lambda: True)
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(module, "find_listening_pid", lambda _: 11)
    # Added helpers are patched on the module for platform-independent tests.
    monkeypatch.setattr(module, "process_parent_pid", lambda _: 10, raising=False)
    identities = {
        10: {"pid": 10, "executable": "C:/hub/.venv/Scripts/pythonw.exe", "creation_identity": "launcher"},
        11: {"pid": 11, "executable": "C:/Python313/pythonw.exe", "creation_identity": "worker"},
    }
    monkeypatch.setattr(module, "process_identity", lambda pid: identities.get(pid), raising=False)

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"ready":true}'

    monkeypatch.setattr(module, "urlopen", lambda *a, **k: Response())
    return instance, identities


@pytest.mark.parametrize("probe", ["hub_ready", "hub_online"])
def test_owned_windows_launcher_worker_is_healthy(supervisor_probe, probe):
    instance, _ = supervisor_probe
    assert getattr(instance, probe)() is True


@pytest.mark.parametrize("failure,reason", [
    (TimeoutError("secret request detail"), "probe_timeout"),
    (URLError(TimeoutError("secret request detail")), "probe_timeout"),
    (URLError(ConnectionRefusedError("secret request detail")), "probe_transport_error"),
    (HTTPError("http://secret", 401, "secret request detail", None, None), "http_status_401"),
])
def test_health_failure_has_safe_actionable_reason(supervisor_probe, monkeypatch, failure, reason):
    instance, _ = supervisor_probe
    def failed_probe(*args, **kwargs):
        raise failure
    monkeypatch.setattr(module, "urlopen", failed_probe)
    assert instance.hub_online() is False
    assert instance.last_health_error == reason
    assert "secret" not in instance.last_health_error


def test_health_probe_recovery_clears_previous_reason(supervisor_probe):
    instance, _ = supervisor_probe
    instance.last_health_error = "probe_timeout"
    assert instance.hub_online() is True
    assert instance.last_health_error == ""


@pytest.mark.parametrize("failure,reason", [
    (TimeoutError("secret response detail"), "probe_timeout"),
    (OSError("secret response detail"), "probe_transport_error"),
])
def test_health_body_read_failure_is_fail_closed(supervisor_probe, monkeypatch, failure, reason):
    instance, _ = supervisor_probe

    class BrokenResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            raise failure

    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: BrokenResponse())
    assert instance.hub_online() is False
    assert instance.last_health_error == reason


@pytest.mark.parametrize("probe", ["hub_ready", "hub_online"])
@pytest.mark.parametrize("unsafe", ["foreign_parent", "foreign_executable", "unknown_identity", "reused_pid", "non_windows", "stale_owner"])
def test_launcher_probe_rejects_unproven_listener(supervisor_probe, monkeypatch, probe, unsafe):
    instance, identities = supervisor_probe
    if unsafe == "foreign_parent":
        monkeypatch.setattr(module, "process_parent_pid", lambda _: 99)
    elif unsafe == "foreign_executable":
        identities[11]["executable"] = "C:/tools/other.exe"
    elif unsafe == "unknown_identity":
        identities.pop(11)
    elif unsafe == "reused_pid":
        worker = dict(identities[11])
        calls = 0

        def identity(pid):
            nonlocal calls
            if pid == 10:
                return identities[10]
            calls += 1
            return worker if calls == 1 else {**worker, "creation_identity": "replacement"}

        monkeypatch.setattr(module, "process_identity", identity)
    elif unsafe == "non_windows":
        monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
    else:
        monkeypatch.setattr(instance, "_owned_hub_child", lambda: False)
    assert getattr(instance, probe)() is False


def test_overload_does_not_accept_foreign_listener(supervisor_probe, monkeypatch):
    instance, _ = supervisor_probe
    monkeypatch.setattr(module, "process_parent_pid", lambda _: 99)

    def overloaded(*args, **kwargs):
        raise HTTPError("http://127.0.0.1:11435/health", 503, "busy", {}, None)

    monkeypatch.setattr(module, "urlopen", overloaded)
    assert instance.hub_online() is False
