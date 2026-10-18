from __future__ import annotations

import runpy
import json
from pathlib import Path

import pytest


def _run_hubctl(monkeypatch, argv, *, online=True, mode_response=None, post_response=None, state_dir=None):
    module = runpy.run_path(str(Path(__file__).parents[1] / "tools" / "hubctl.py"))
    globals_ = module["main"].__globals__
    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))

        def _online(self, timeout=None):
            return online

        def get(self, path, **kwargs):
            calls.append(("get", path, kwargs))
            if path == "/api/status":
                return {"hub_pid": 12, "version": "test", "ollama_online": True}
            return mode_response if mode_response is not None else {"success": True, "mode": "active"}

        def post(self, path, payload, **kwargs):
            calls.append(("post", path, payload, kwargs))
            if post_response is not None:
                return post_response
            response = {"success": True, "mode": payload["mode"]}
            if payload["mode"] == "gaming":
                response["runtime_unload"] = {"success": True}
                response["accelerator_release"] = {"success": True}
            return response

    monkeypatch.setitem(globals_, "HubClient", Client)
    monkeypatch.setitem(globals_, "load_config", lambda _path: {
        "ollama": {"enabled": True},
        "server": {"state_dir": str(state_dir or Path.cwd() / ".test-state")},
    })
    monkeypatch.setitem(globals_, "llama_cpp_backend_selection", lambda _config: "ollama")
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


@pytest.mark.parametrize(("argv", "expected_mode"), [
    (("pause",), "gaming"),
    (("resume",), "active"),
    (("mode", "maintenance"), "maintenance"),
])
def test_hubctl_sets_mode_offline_without_starting_server(monkeypatch, capsys, tmp_path, argv, expected_mode):
    state_dir = tmp_path / "state"
    result, calls = _run_hubctl(monkeypatch, argv, online=False, state_dir=state_dir)

    captured = capsys.readouterr()
    if expected_mode == "gaming":
        assert result == 1
        assert "Mode persisted as gaming." in captured.out
        assert "Mode transition incomplete: VRAM unload, accelerator release." in captured.err
    else:
        assert result == 0
        assert f"Mode set to {expected_mode}" in captured.out
        assert not captured.err
    assert json.loads((state_dir / "operational_mode.json").read_text(encoding="utf-8"))["mode"] == expected_mode
    assert not any(call[0] == "post" for call in calls)
    assert any(call[0] == "client" and call[1].get("auto_start") is False for call in calls)


@pytest.mark.parametrize("action", ["mode", "status"])
def test_hubctl_reads_persisted_mode_offline(monkeypatch, capsys, tmp_path, action):
    from local_ai_hub.operational_mode import set_operational_mode

    state_dir = tmp_path / "state"
    set_operational_mode(state_dir, "gaming")
    result, calls = _run_hubctl(monkeypatch, [action], online=False, state_dir=state_dir)

    assert result == 0
    assert "Activity mode: gaming" in capsys.readouterr().out
    assert not any(call[0] in {"get", "post"} for call in calls)
    assert any(call[0] == "client" and call[1].get("auto_start") is False for call in calls)


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


def test_hubctl_pause_warns_when_vram_unload_is_incomplete(monkeypatch, capsys):
    result, _calls = _run_hubctl(
        monkeypatch,
        ["pause"],
        post_response={
            "success": True,
            "mode": "gaming",
            "runtime_unload": {"success": False, "backend_available": False},
            "accelerator_release": {"success": True, "verified": True},
        },
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "Mode persisted as gaming." in captured.out
    assert "Mode transition incomplete: VRAM unload." in captured.err
    assert "Mode set to gaming" not in captured.out


@pytest.mark.parametrize(
    ("argv", "mode", "outcomes", "expected_failure"),
    [
        (
            ["mode", "gaming"],
            "gaming",
            {
                "runtime_unload": {"success": True},
                "accelerator_release": {"success": False},
            },
            "accelerator release",
        ),
        (
            ["mode", "gaming"],
            "gaming",
            {
                "runtime_unload": {"success": True},
                "accelerator_release": {"success": True},
                "job_cancellation": {"success": False},
            },
            "job cancellation",
        ),
        (
            ["mode", "maintenance"],
            "maintenance",
            {"job_cancellation": {"success": False}},
            "job cancellation",
        ),
    ],
)
def test_hubctl_reports_partial_mode_transition_failures(
    monkeypatch, capsys, argv, mode, outcomes, expected_failure
):
    post_response = {"success": True, "mode": mode, **outcomes}
    result, _calls = _run_hubctl(
        monkeypatch,
        argv,
        post_response=post_response,
    )
    captured = capsys.readouterr()

    assert result == 1
    assert f"Mode persisted as {mode}." in captured.out
    assert f"Mode transition incomplete: {expected_failure}." in captured.err
    assert f"Mode set to {mode}" not in captured.out


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
    assert ("client", {"config_path": str(config_path), "auto_start": False}) in calls
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


def test_hubctl_status_remains_successful_when_mode_endpoint_fails(monkeypatch, capsys):
    result, _calls = _run_hubctl(
        monkeypatch,
        ["status"],
        mode_response={"success": False, "error": "mode endpoint unavailable", "retryable": True},
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "Local AI Hub vtest - Online" in output
    assert "Activity mode: Unknown" in output
