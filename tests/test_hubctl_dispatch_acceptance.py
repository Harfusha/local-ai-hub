from __future__ import annotations

import sys
import types
from pathlib import Path

import tools
import tools.hubctl as hubctl


def _invoke(monkeypatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["hubctl.py", *args])
    return hubctl.main()


def test_hubctl_status_dispatch_reports_offline(monkeypatch, capsys):
    monkeypatch.setattr(hubctl, "status", lambda *_args: {"running": False})
    monkeypatch.setattr(hubctl, "load_config", lambda *_args: {})

    assert _invoke(monkeypatch, "status") == 0
    assert "Local AI Hub: Offline (stopped)" in capsys.readouterr().out


def test_hubctl_start_dispatch_calls_start_and_reports_result(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(hubctl, "start", lambda: calls.append("start") or True)

    assert _invoke(monkeypatch, "start") == 0
    assert calls == ["start"]
    assert capsys.readouterr().out.strip() == "started"


def test_hubctl_stop_dispatch_calls_stop_and_reports_failure(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(hubctl, "stop", lambda: calls.append("stop") or False)

    assert _invoke(monkeypatch, "stop") == 1
    assert calls == ["stop"]
    assert capsys.readouterr().out.strip() == "stop failed"


def test_hubctl_restart_dispatch_stops_before_starting(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(hubctl, "stop", lambda: calls.append("stop") or True)
    monkeypatch.setattr(hubctl, "start", lambda: calls.append("start") or True)

    assert _invoke(monkeypatch, "restart") == 0
    assert calls == ["stop", "start"]
    assert capsys.readouterr().out.strip() == "restarted"


def test_hubctl_watch_dispatch_calls_monitor_and_returns_status(monkeypatch):
    calls = []
    monkeypatch.setattr(
        hubctl.subprocess,
        "call",
        lambda args: calls.append(args) or 7,
    )

    assert _invoke(monkeypatch, "watch") == 7
    assert len(calls) == 1
    assert calls[0][0] == sys.executable
    assert Path(calls[0][1]) == hubctl.ROOT / "tools" / "monitor.py"


def test_hubctl_dashboard_dispatch_prints_client_url(monkeypatch, capsys):
    class Client:
        base_url = "http://127.0.0.1:11436"

    monkeypatch.setattr(hubctl, "client", lambda: Client())

    assert _invoke(monkeypatch, "dashboard") == 0
    assert capsys.readouterr().out.strip() == "http://127.0.0.1:11436/dashboard"


def test_hubctl_service_status_dispatch_reads_status_file(monkeypatch, tmp_path, capsys):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    payload = '{"running":true,"pid":321}'
    (state_dir / "supervisor.status.json").write_text(payload, encoding="utf-8")
    monkeypatch.setattr(
        hubctl,
        "load_config",
        lambda *_args: {"server": {"state_dir": str(state_dir)}},
    )

    assert _invoke(monkeypatch, "service-status") == 0
    assert capsys.readouterr().out.strip() == payload


def test_hubctl_clean_dispatch_forwards_full_clean_flag(monkeypatch, capsys):
    clean_calls = []
    clean_module = types.ModuleType("tools.clean")
    clean_module.clean = lambda root, all_clean=False: clean_calls.append((root, all_clean)) or (2, 3)
    monkeypatch.setitem(sys.modules, "tools.clean", clean_module)
    monkeypatch.setattr(tools, "clean", clean_module, raising=False)

    assert _invoke(monkeypatch, "clean", "--ports") == 0
    assert clean_calls == [(hubctl.ROOT, True)]
    assert "Cleaned 2 directories and 3 cache/build files." in capsys.readouterr().out


def test_hubctl_generate_dispatch_calls_generator_and_install(monkeypatch, capsys):
    generated = []
    configured = []
    generator_module = types.ModuleType("local_ai_hub.generator")
    generator_module.write_all_generated = lambda config, root, python_bin: generated.append(
        (config, root, python_bin)
    ) or {"files": ["generated"]}
    setup_module = types.ModuleType("tools.setup")
    setup_module.venv_python = lambda _root: Path(sys.executable)
    setup_module.expand = lambda _path: hubctl.ROOT
    setup_module.configure_agents = lambda *args: configured.append(args)
    monkeypatch.setitem(sys.modules, "local_ai_hub.generator", generator_module)
    monkeypatch.setitem(sys.modules, "tools.setup", setup_module)
    monkeypatch.setattr(tools, "setup", setup_module, raising=False)
    monkeypatch.setattr(
        hubctl,
        "load_config",
        lambda *_args: {
            "setup": {
                "install_dir": str(hubctl.ROOT),
                "install_agent_configs": False,
            }
        },
    )

    assert _invoke(monkeypatch, "generate", "--install") == 0
    assert len(generated) == 1
    assert generated[0][1] == hubctl.ROOT
    assert generated[0][2] == Path(sys.executable)
    assert len(configured) == 1
    assert '"success": true' in capsys.readouterr().out
