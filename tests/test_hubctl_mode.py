from __future__ import annotations

import runpy
import json
import sys
import types
from pathlib import Path

import pytest


def _run_hubctl(monkeypatch, argv, *, online=True, mode_response=None, post_response=None, state_dir=None, mode_setter=None):
    module = runpy.run_path(str(Path(__file__).parents[1] / "tools" / "hubctl.py"))
    globals_ = module["main"].__globals__
    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))

        def _online(self):
            return online

        def get(self, path, **kwargs):
            calls.append(("get", path, kwargs))
            if path == "/api/status":
                return {"hub_pid": 12, "version": "test", "ollama_online": True}
            return mode_response if mode_response is not None else {"success": True, "mode": "active"}

        def post(self, path, payload, **kwargs):
            calls.append(("post", path, payload, kwargs))
            return post_response if post_response is not None else {"success": True, "mode": payload["mode"]}

    monkeypatch.setitem(globals_, "HubClient", Client)
    def load_test_config(_path):
        calls.append(("load_config", _path))
        return {"ollama": {"enabled": True}, "server": {"state_dir": str(state_dir or Path("unused-test-state"))}}

    monkeypatch.setitem(globals_, "load_config", load_test_config)
    monkeypatch.setitem(globals_, "llama_cpp_backend_selection", lambda _config: "ollama")
    if mode_setter is not None:
        mode_module = types.ModuleType("local_ai_hub.operational_mode")
        mode_module.set_operational_mode = mode_setter
        monkeypatch.setitem(sys.modules, "local_ai_hub.operational_mode", mode_module)
    monkeypatch.setattr("sys.argv", ["hubctl.py", *argv])
    result = module["main"]()
    return result, calls


@pytest.mark.parametrize(("action", "expected_mode"), [("pause", "gaming"), ("resume", "active")])
def test_hubctl_pause_resume_use_authorized_mode_endpoint(monkeypatch, capsys, action, expected_mode):
    result, calls = _run_hubctl(monkeypatch, [action])

    assert result == 0
    assert ("post", "/api/admin/mode", {"mode": expected_mode}, {"timeout": 3.0}) in calls
    assert f"Mode set to {expected_mode}" in capsys.readouterr().out
    assert any(call[0] == "client" and call[1].get("auto_start") is False for call in calls)


def test_hubctl_mode_rejects_invalid_mode_before_request(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run_hubctl(monkeypatch, ["mode", "turbo"])

    assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.parametrize(("action", "expected_mode"), [("pause", "gaming"), ("resume", "active"), ("mode", "gaming")])
def test_hubctl_mode_persists_offline_without_starting_server(monkeypatch, capsys, tmp_path, action, expected_mode):
    config_path = tmp_path / "alternate.toml"
    argv = (["mode", expected_mode, "--config", str(config_path)] if action == "mode" else [action, "--config", str(config_path)])
    result, calls = _run_hubctl(monkeypatch, argv, online=False, state_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert "saved offline" in captured.out.lower()
    if expected_mode == "gaming":
        assert "VRAM unload was incomplete" in captured.err
    assert not any(call[0] == "post" for call in calls)
    assert any(call[0] == "client" and call[1].get("auto_start") is False for call in calls)
    assert ("load_config", str(config_path)) in calls
    snapshot = json.loads((tmp_path / "operational_mode.json").read_text(encoding="utf-8"))
    assert snapshot["mode"] == expected_mode
    assert snapshot["revision"] == 1
    assert snapshot["degraded"] is False
    assert not list(tmp_path.glob(".operational_mode-*.tmp"))


def test_hubctl_offline_mode_uses_shared_set_operational_mode_when_available(monkeypatch, capsys, tmp_path):
    calls = []

    def setter(state_dir, mode):
        calls.append((Path(state_dir), mode))
        return {"mode": mode, "revision": 1}

    result, _calls = _run_hubctl(
        monkeypatch,
        ["mode", "gaming"],
        online=False,
        state_dir=tmp_path,
        mode_setter=setter,
    )

    assert result == 0
    assert calls == [(tmp_path, "gaming")]
    assert "Mode saved offline: gaming" in capsys.readouterr().out


def test_hubctl_offline_mode_reads_persisted_state_without_http(monkeypatch, capsys, tmp_path):
    path = tmp_path / "operational_mode.json"
    original = {"mode": "gaming", "revision": 4, "updated_at": "2026-09-29T10:00:00+00:00", "degraded": False, "error": ""}
    path.write_text(json.dumps(original), encoding="utf-8")

    result, calls = _run_hubctl(monkeypatch, ["mode", "--config", str(tmp_path / "alternate.toml")], online=False, state_dir=tmp_path)

    assert result == 0
    assert "Activity mode: gaming" in capsys.readouterr().out
    assert not any(call[0] in {"get", "post"} for call in calls)
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_hubctl_offline_resume_increments_existing_persistent_state(monkeypatch, capsys, tmp_path):
    path = tmp_path / "operational_mode.json"
    path.write_text(
        json.dumps({"mode": "maintenance", "revision": 6, "updated_at": "2026-09-29T10:00:00+00:00", "degraded": False, "error": ""}),
        encoding="utf-8",
    )

    result, calls = _run_hubctl(monkeypatch, ["resume"], online=False, state_dir=tmp_path)

    assert result == 0
    assert "Mode saved offline: active" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8"))["mode"] == "active"
    assert json.loads(path.read_text(encoding="utf-8"))["revision"] == 7
    assert not any(call[0] in {"get", "post"} for call in calls)


def test_hubctl_offline_mode_refuses_to_overwrite_invalid_state(monkeypatch, capsys, tmp_path):
    path = tmp_path / "operational_mode.json"
    invalid = '{"mode":"gaming","revision":0,"updated_at":null}'
    path.write_text(invalid, encoding="utf-8")

    result, _calls = _run_hubctl(monkeypatch, ["pause"], online=False, state_dir=tmp_path)

    assert result == 1
    assert "invalid" in capsys.readouterr().err.lower()
    assert path.read_text(encoding="utf-8") == invalid


def test_hubctl_offline_status_displays_persisted_mode(monkeypatch, capsys, tmp_path):
    (tmp_path / "operational_mode.json").write_text(
        json.dumps({"mode": "maintenance", "revision": 2, "updated_at": "2026-09-29T10:00:00+00:00", "degraded": False, "error": ""}),
        encoding="utf-8",
    )

    result, calls = _run_hubctl(monkeypatch, ["status", "--config", str(tmp_path / "alternate.toml")], online=False, state_dir=tmp_path)

    assert result == 0
    output = capsys.readouterr().out
    assert "Local AI Hub: Offline" in output
    assert "Activity mode: maintenance" in output
    assert not any(call[0] in {"get", "post"} for call in calls)


def test_hubctl_mode_reports_unauthorized_response(monkeypatch, capsys):
    result, _calls = _run_hubctl(
        monkeypatch,
        ["resume"],
        post_response={"success": False, "error": "unauthorized", "status_code": 401},
    )

    assert result == 1
    assert "401" in capsys.readouterr().err


def test_hubctl_mode_reports_server_rejection(monkeypatch, capsys):
    result, _calls = _run_hubctl(
        monkeypatch,
        ["mode", "gaming"],
        post_response={"success": False, "error": "invalid mode", "status_code": 400},
    )

    assert result == 1
    assert "invalid mode" in capsys.readouterr().err


def test_hubctl_mode_does_not_assume_requested_mode_without_server_confirmation(monkeypatch, capsys):
    result, _calls = _run_hubctl(
        monkeypatch,
        ["mode", "gaming"],
        post_response={"success": True},
    )

    assert result == 1
    assert "invalid mode returned by server" in capsys.readouterr().err


def test_hubctl_mode_read_requires_server_mode(monkeypatch, capsys):
    result, _calls = _run_hubctl(monkeypatch, ["mode"], mode_response={"success": True})

    assert result == 1
    assert "invalid mode returned by server" in capsys.readouterr().err


def test_hubctl_mode_reads_current_mode(monkeypatch, capsys):
    result, calls = _run_hubctl(monkeypatch, ["mode"])

    assert result == 0
    assert ("get", "/api/mode", {"timeout": 3.0}) in calls
    assert "Activity mode: active" in capsys.readouterr().out


def test_hubctl_mode_uses_explicit_config_path(monkeypatch, capsys, tmp_path):
    config_path = tmp_path / "alternate-hub.toml"

    result, calls = _run_hubctl(monkeypatch, ["mode", "gaming", "--config", str(config_path)])

    assert result == 0
    assert ("client", {"tenant": "hubctl", "config_path": str(config_path), "auto_start": False}) in calls
    assert "Mode set to gaming" in capsys.readouterr().out


def test_hubctl_status_uses_explicit_config_path_for_all_requests(monkeypatch, capsys, tmp_path):
    config_path = tmp_path / "alternate-hub.toml"

    result, calls = _run_hubctl(monkeypatch, ["status", "--config", str(config_path)])

    assert result == 0
    client_calls = [call[1] for call in calls if call[0] == "client"]
    assert client_calls
    assert all(call.get("config_path") == str(config_path) for call in client_calls)
    assert "Activity mode: active" in capsys.readouterr().out


def test_hubctl_status_includes_current_mode(monkeypatch, capsys):
    result, calls = _run_hubctl(monkeypatch, ["status"])

    assert result == 0
    assert ("get", "/api/mode", {"timeout": 3.0}) in calls
    assert "Activity mode: active" in capsys.readouterr().out
