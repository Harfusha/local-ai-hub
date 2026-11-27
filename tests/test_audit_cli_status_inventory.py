from tools.hubctl import status_inventory_lines


def test_cli_does_not_turn_missing_inventory_into_zero():
    models, agent = status_inventory_lines({})
    assert "unreported" in models.lower()
    assert "unreported" in agent.lower()
    assert "0 installed" not in models
    assert "0 tasks" not in agent


def test_cli_reports_explicit_empty_inventory_and_distinguishes_stale():
    models, agent = status_inventory_lines({"installed_models": [], "agent_state": {"tasks": [], "leases": []}})
    assert "0 installed" in models
    assert "0 reported tasks" in agent
    models, _ = status_inventory_lines({"installed_models": [], "snapshot_stale": True})
    assert "stale" in models.lower()
    assert "0 installed" not in models


def test_cli_rejects_malformed_or_explicitly_unavailable_models():
    for value in ({"installed_models": [7]}, {"installed_models": [], "installed_models_available": False}):
        models, _ = status_inventory_lines(value)
        assert "unreported" in models.lower()
        assert "0 installed" not in models


def test_stop_requires_owned_service_receipt_not_http_pid(monkeypatch):
    import subprocess
    from tools import hubctl

    def unexpected_status(*args, **kwargs):
        raise AssertionError("HTTP status PID must not be consulted for termination")

    monkeypatch.setattr(hubctl, "status", unexpected_status)
    monkeypatch.setattr(hubctl.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 1, stdout='{"stopped":false}', stderr=""))
    monkeypatch.setattr(hubctl, "HubClient", unexpected_status)
    assert hubctl.stop() is False


def test_stop_accepts_only_explicit_detached_service_receipt():
    import json
    import subprocess
    from tools import hubctl

    reason = "managed_user_unit_not_installed"
    receipt = {
        "stopped": True, "supervisor_stopped": True, "hub_stopped": True,
        "managed_ollama_stopped": True, "port_listener_pid": None,
        "errors": [reason], "service_manager": {"supported": False, "reason": reason},
    }
    def confirmed(value, returncode=1):
        return hubctl._confirmed_service_stop(
            subprocess.CompletedProcess([], returncode, stdout=json.dumps(value), stderr=""))
    assert confirmed(receipt)
    for invalid in ({"stopped": False}, {"supervisor_stopped": False}, {"hub_stopped": False},
                    {"managed_ollama_stopped": False}, {"port_listener_pid": 123},
                    {"errors": [reason, "disable_marker_write_failed"]},
                    {"service_manager": {"supported": True, "reason": reason}}):
        assert not confirmed({**receipt, **invalid})
    assert not confirmed(receipt, 124)
    assert not confirmed({"success": True}, 0)
    assert hubctl._confirmed_service_stop(subprocess.CompletedProcess([], 0, stdout="stopped\n", stderr=""))


def test_stop_checks_readiness_without_autostart_after_verified_receipt(monkeypatch):
    import subprocess
    from unittest.mock import MagicMock
    from tools import hubctl

    monkeypatch.setattr(hubctl.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, stdout="stopped\n", stderr=""))
    factory = MagicMock()
    monkeypatch.setattr(hubctl, "HubClient", factory)
    client = factory.return_value
    client._online.return_value = False
    assert hubctl.stop()
    assert factory.call_args.kwargs["auto_start"] is False
    client.close.assert_called_once()
    client._online.return_value = True
    assert not hubctl.stop()
