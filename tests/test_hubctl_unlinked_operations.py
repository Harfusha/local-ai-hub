"""Focused CLI behavior checks for hubctl actions missing inventory links."""

import json
import sys
from pathlib import Path

from tools import hubctl


def test_hubctl_clean_dispatches_cleanup_and_json_output(monkeypatch, capsys, tmp_path):
    calls = []

    def clean(root, *, all_clean=False, dry_run=False):
        calls.append((root, all_clean, dry_run))
        return 2, 3

    monkeypatch.setattr(hubctl, "ROOT", tmp_path)
    monkeypatch.setattr("tools.clean.clean", clean)
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "clean", "--json"])

    result = hubctl.main()

    assert result == 0
    assert calls == [(tmp_path, False, False)]
    assert json.loads(capsys.readouterr().out) == {
        "success": True,
        "dirs_removed": 2,
        "files_removed": 3,
    }


def test_hubctl_dashboard_prints_configured_url(monkeypatch, capsys):
    class Client:
        base_url = "http://127.0.0.1:11436"

    calls = []
    monkeypatch.setattr(hubctl, "client", lambda: calls.append("client") or Client())
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "dashboard"])

    result = hubctl.main()

    assert result == 0
    assert calls == ["client"]
    assert capsys.readouterr().out == "http://127.0.0.1:11436/dashboard\n"


def test_hubctl_generate_dispatches_writers_and_optional_agent_install(
    monkeypatch, capsys, tmp_path
):
    config_path = tmp_path / "config.toml"
    install_dir = tmp_path / "agent-install"
    root = tmp_path / "hub-root"
    python_bin = tmp_path / "missing-venv-python"
    config = {"setup": {"install_dir": str(install_dir), "install_agent_configs": False}}
    writes = []
    installs = []
    monkeypatch.setattr(hubctl, "ROOT", root)
    monkeypatch.setattr(hubctl, "load_config", lambda path: config)
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "generate", "--config", str(config_path), "--install"])

    from local_ai_hub import generator
    from tools import setup as setup_mod

    monkeypatch.setattr(generator, "write_all_generated", lambda cfg, dest, py: writes.append((cfg, dest, py)) or {"written": 1})
    monkeypatch.setattr(setup_mod, "venv_python", lambda venv: python_bin)
    monkeypatch.setattr(setup_mod, "expand", lambda value: install_dir)
    monkeypatch.setattr(
        setup_mod,
        "configure_agents",
        lambda dest, py, *args: installs.append((dest, py, args)),
    )

    result = hubctl.main()

    assert result == 0
    assert writes == [
        (config, root, Path(sys.executable)),
        (config, install_dir, Path(sys.executable)),
    ]
    assert installs == [(install_dir, Path(sys.executable), (None, None, config))]
    assert json.loads(capsys.readouterr().out) == {
        "success": True,
        "generated": {"written": 1},
    }


def test_hubctl_restart_stops_then_starts_and_reports_result(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(hubctl, "stop", lambda: calls.append("stop") or True)
    monkeypatch.setattr(hubctl, "start", lambda: calls.append("start") or True)
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "restart"])

    result = hubctl.main()

    assert result == 0
    assert calls == ["stop", "start"]
    assert capsys.readouterr().out == "restarted\n"


def test_hubctl_service_status_reads_configured_supervisor_file(
    monkeypatch, capsys, tmp_path
):
    config_path = tmp_path / "config.toml"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    payload = '{"running": true, "pid": 42}'
    (state_dir / "supervisor.status.json").write_text(payload, encoding="utf-8")
    monkeypatch.setattr(
        hubctl,
        "load_config",
        lambda path: {"server": {"state_dir": str(state_dir)}},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["hubctl.py", "service-status", "--config", str(config_path)],
    )

    result = hubctl.main()

    assert result == 0
    assert capsys.readouterr().out == payload + "\n"


def test_hubctl_start_dispatches_start_and_reports_success(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(hubctl, "start", lambda: calls.append("start") or True)
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "start"])

    result = hubctl.main()

    assert result == 0
    assert calls == ["start"]
    assert capsys.readouterr().out == "started\n"


def test_hubctl_status_reports_offline_without_starting_service(
    monkeypatch, capsys, tmp_path
):
    config_path = tmp_path / "config.toml"
    calls = []
    starts = []
    monkeypatch.setattr(
        hubctl,
        "status",
        lambda config=None: calls.append(config) or {"running": False},
    )
    monkeypatch.setattr(hubctl, "start", lambda *args: starts.append(args) or True)
    monkeypatch.setattr(hubctl, "load_config", lambda path: {})
    monkeypatch.setattr(
        sys,
        "argv",
        ["hubctl.py", "status", "--config", str(config_path)],
    )

    result = hubctl.main()

    assert result == 0
    assert len(calls) == 1
    assert calls[0] in (None, config_path, str(config_path))
    assert starts == []
    assert capsys.readouterr().out.splitlines() in (
        ["Local AI Hub: Offline (stopped)"],
        [
            "Local AI Hub: Offline (stopped)",
            "Activity mode: Unknown (Local AI Hub is offline or unreachable)",
        ],
    )


def test_hubctl_stop_dispatches_stop_and_reports_success(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(hubctl, "stop", lambda: calls.append("stop") or True)
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "stop"])

    result = hubctl.main()

    assert result == 0
    assert calls == ["stop"]
    assert capsys.readouterr().out == "stopped\n"


def test_hubctl_watch_dispatches_monitor_and_returns_its_exit_code(
    monkeypatch, tmp_path
):
    root = tmp_path / "hub-root"
    calls = []
    monkeypatch.setattr(hubctl, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "watch"])
    monkeypatch.setattr(
        hubctl.subprocess,
        "call",
        lambda argv: calls.append(argv) or 7,
    )

    result = hubctl.main()

    assert result == 7
    assert calls == [[sys.executable, str(root / "tools" / "monitor.py")]]
