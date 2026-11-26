"""Contract tests for the native desktop controller (no service or display)."""
from unittest.mock import MagicMock, patch

import pytest

from tools import desktop


def test_read_never_autostarts_or_calls_offline_hub():
    with patch.object(desktop, "HubClient") as factory:
        factory.return_value._online.return_value = False
        control = desktop.HubControl("config.toml")
        with pytest.raises(RuntimeError, match="not reachable"):
            control.read("Overview")
        factory.assert_called_once_with(config_path="config.toml", auto_start=False)
        factory.return_value.get.assert_not_called()
        factory.return_value.close.assert_called_once()


def test_scoped_read_requires_explicit_root():
    control = desktop.HubControl()
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(ValueError, match="explicit"):
            control.read("Tasks")
        factory.assert_not_called()


def test_scoped_read_encodes_root(tmp_path):
    root = tmp_path / "space & name"
    root.mkdir()
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": True, "tasks": []}
        result = desktop.HubControl().read("Tasks", str(root))
        assert result["tasks"] == []
        from urllib.parse import parse_qs, urlsplit
        url = client.get.call_args.args[0]
        assert parse_qs(urlsplit(url).query)["root"] == [str(root.resolve())]
        client.close.assert_called_once()


@pytest.mark.parametrize("action", ["stop", "restart"])
def test_lifecycle_reuses_existing_cli(action):
    control = desktop.HubControl("config.toml")
    with patch.object(control, "_cli", return_value="completed") as cli:
        assert control.lifecycle(action) == "completed"
        cli.assert_called_once_with((action,), timeout=760)


def test_start_when_offline():
    control = desktop.HubControl()
    with patch.object(control, "online", return_value=False), patch.object(
        control, "_cli", return_value="started"
    ) as cli:
        assert control.lifecycle("start") == "started"
        cli.assert_called_once_with(("start",), timeout=760)


def test_start_is_idempotent_if_online():
    control = desktop.HubControl()
    with patch.object(control, "online", return_value=True), patch.object(control, "_cli") as cli:
        assert control.lifecycle("start") == "Hub is already online."
        cli.assert_not_called()


@pytest.mark.parametrize("value", ["command", "start && anything", "--help"])
def test_rejects_unregistered_lifecycle_and_modes(value):
    control = desktop.HubControl()
    with patch.object(control, "_cli") as cli:
        with pytest.raises(ValueError):
            control.lifecycle(value)
        with pytest.raises(ValueError):
            control.mode(value)
        cli.assert_not_called()


def test_cli_uses_fixed_argv_no_shell():
    control = desktop.HubControl("config.toml")
    with patch.object(desktop.subprocess, "run") as run:
        run.return_value = MagicMock(returncode=0, stdout="started", stderr="")
        assert control._cli(("start",), 760) == "started"
        args, kwargs = run.call_args
        assert args[0] == [desktop.sys.executable, str(desktop.ROOT / "tools" / "hubctl.py"), "start"]
        assert not kwargs.get("shell", False)
        assert kwargs["env"]["LOCAL_AI_CONFIG"] == "config.toml"


def test_api_failure_is_not_rendered_as_success():
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": False, "error": "denied"}
        with pytest.raises(RuntimeError, match="denied"):
            desktop.HubControl().read("Overview")
        client.close.assert_called_once()


def test_maintenance_requires_explicit_success():
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.post.return_value = {"success": False, "error": "denied"}
        with pytest.raises(RuntimeError, match="denied"):
            desktop.HubControl().maintenance("Purge expired cache (7 days)")
        assert client.post.call_args.args == ("/api/maintenance/purge_cache", {"days": 7})
        client.close.assert_called_once()


def test_unknown_maintenance_is_rejected_before_transport():
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(KeyError):
            desktop.HubControl().maintenance("arbitrary shell")
        factory.assert_not_called()
