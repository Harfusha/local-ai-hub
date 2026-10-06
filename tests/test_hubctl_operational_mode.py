from __future__ import annotations

import json
import multiprocessing
import sys

import pytest

from tools import hubctl
from local_ai_hub.operational_mode import load_operational_mode


def _read_mode_in_fresh_process(state_dir, connection):
    try:
        snapshot = load_operational_mode(state_dir)
        connection.send((snapshot.mode, snapshot.revision, snapshot.degraded))
    finally:
        connection.close()


def test_pause_and_resume_persist_offline_when_hub_is_unavailable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        hubctl,
        "load_config",
        lambda _path=None: {"server": {"state_dir": str(tmp_path)}},
    )
    class OfflineClient:
        def __init__(self, **_kwargs):
            pass

        def _online(self):
            return False

    monkeypatch.setattr(hubctl, "HubClient", OfflineClient)

    monkeypatch.setattr(sys, "argv", ["hubctl", "pause", "--json"])
    assert hubctl.main() == 0
    paused = json.loads(capsys.readouterr().out)
    assert paused["success"] is True
    assert paused["mode"] == "maintenance"
    assert paused["offline"] is True
    assert load_operational_mode(tmp_path).mode == "maintenance"

    monkeypatch.setattr(sys, "argv", ["hubctl", "resume", "--json"])
    assert hubctl.main() == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["success"] is True
    assert resumed["mode"] == "active"
    assert resumed["offline"] is True
    assert load_operational_mode(tmp_path).mode == "active"


@pytest.mark.parametrize("mode", ["active", "gaming", "maintenance"])
def test_mode_command_persists_any_mode_when_hub_is_offline(
    monkeypatch, tmp_path, capsys, mode
):
    monkeypatch.setattr(
        hubctl,
        "load_config",
        lambda _path=None: {"server": {"state_dir": str(tmp_path)}},
    )
    constructors = []

    class OfflineClient:
        def __init__(self, **_kwargs):
            constructors.append(_kwargs)

        def _online(self):
            return False

        def post(self, *_args, **_kwargs):
            raise AssertionError("offline mode sent a mutation")

    monkeypatch.setattr(hubctl, "HubClient", OfflineClient)
    monkeypatch.setattr(sys, "argv", ["hubctl", "mode", mode, "--json"])

    assert hubctl.main() == 0

    result = json.loads(capsys.readouterr().out)
    assert result["success"] is True
    assert result["offline"] is True
    assert result["mode"] == mode
    assert load_operational_mode(tmp_path).mode == mode
    assert constructors[0]["auto_start"] is False


def test_offline_hubctl_mode_survives_fresh_process_restart(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        hubctl,
        "load_config",
        lambda _path=None: {"server": {"state_dir": str(tmp_path)}},
    )

    class OfflineClient:
        def __init__(self, **_kwargs):
            pass

        def _online(self):
            return False

    monkeypatch.setattr(hubctl, "HubClient", OfflineClient)
    monkeypatch.setattr(sys, "argv", ["hubctl", "mode", "gaming", "--json"])

    assert hubctl.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["success"] is True
    assert result["offline"] is True
    assert result["mode"] == "gaming"

    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    child = context.Process(
        target=_read_mode_in_fresh_process,
        args=(str(tmp_path), writer),
    )
    child.start()
    writer.close()
    try:
        assert reader.poll(10), "fresh process did not load persisted mode"
        snapshot = reader.recv()
    finally:
        reader.close()
        child.join(10)
        if child.is_alive():
            child.terminate()
            child.join(5)

    assert child.exitcode == 0
    assert snapshot == ("gaming", result["revision"], False)


def test_mode_command_routes_live_transition_through_mode_api(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        hubctl,
        "load_config",
        lambda _path=None: {"server": {"state_dir": str(tmp_path)}},
    )
    calls = []

    constructors = []

    class OnlineClient:
        def __init__(self, **_kwargs):
            constructors.append(_kwargs)

        def _online(self):
            return True

        def post(self, path, payload, **kwargs):
            calls.append((path, payload, kwargs))
            return {"success": True, "mode": "gaming", "revision": 2}

    monkeypatch.setattr(hubctl, "HubClient", OnlineClient)
    monkeypatch.setattr(sys, "argv", ["hubctl", "mode", "gaming", "--json"])

    assert hubctl.main() == 0

    result = json.loads(capsys.readouterr().out)
    assert result["success"] is True
    assert result["offline"] is False
    assert result["revision"] == 2
    assert calls[0][0:2] == ("/api/mode", {"mode": "gaming"})
    assert constructors[0]["auto_start"] is False
    assert load_operational_mode(tmp_path).mode == "active"


def test_mode_command_does_not_fallback_after_uncertain_live_transition(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        hubctl,
        "load_config",
        lambda _path=None: {"server": {"state_dir": str(tmp_path)}},
    )

    class OnlineClient:
        def __init__(self, **_kwargs):
            pass

        def _online(self):
            return True

        def post(self, *_args, **_kwargs):
            return {
                "success": False,
                "error": "request delivery outcome is unknown",
                "outcome_unknown": True,
            }

    monkeypatch.setattr(hubctl, "HubClient", OnlineClient)
    monkeypatch.setattr(sys, "argv", ["hubctl", "mode", "gaming", "--json"])

    assert hubctl.main() == 1

    result = json.loads(capsys.readouterr().out)
    assert result["offline"] is False
    assert result["outcome_unknown"] is True
    assert load_operational_mode(tmp_path).mode == "active"
