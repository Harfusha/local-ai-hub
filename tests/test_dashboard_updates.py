import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import dashboard_updates as updates
from local_ai_hub import http_server


VERSION = "6.1.2"
REVISION = "a" * 40


def controller(tmp_path, monkeypatch):
    prefix = tmp_path / ".venv"
    prefix.mkdir()
    script = tmp_path / "tools/auto_update.py"
    script.parent.mkdir()
    script.touch()
    config = tmp_path / "config.toml"
    config.touch()
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "_base_executable", sys.executable)
    return updates.DashboardUpdates(str(config)), script


def test_dashboard_requires_fresh_exact_candidate_and_pins_launcher(tmp_path, monkeypatch):
    control, path = controller(tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(updates, "_launch", lambda root, args, job: started.append(args))
    monkeypatch.setattr(updates, "_check_release", lambda command: {
        "success": True, "status": "update_available", "target_version": VERSION,
        "revision": REVISION, "version_before": "6.1.1",
    })
    control.status()
    control._thread.join(timeout=2)
    assert control.status()["check"]["target_version"] == VERSION
    with pytest.raises(ValueError, match="review"):
        control.install(VERSION, "b" * 40)
    assert not started
    assert control.install(VERSION, REVISION)["status"] == "queued"
    assert started == [[str(Path(sys.executable)), "-I", "-B", str(path), "--apply",
                        "--expect-version", VERSION, "--expect-revision", REVISION, "--desktop"]]
    with pytest.raises(ValueError, match="already"):
        control.install(VERSION, REVISION)


def test_dashboard_reads_completion_from_previous_process(tmp_path, monkeypatch):
    control, _ = controller(tmp_path, monkeypatch)
    monkeypatch.setattr(updates, "_check_release", lambda command: {"status": "up_to_date"})
    (tmp_path / "auto-update-desktop.json").write_text(json.dumps({
        "success": True, "status": "installed", "target_version": VERSION,
    }), encoding="utf-8")
    assert control.status()["report"]["target_version"] == VERSION
    assert control.status()["report"]["status"] == "installed"


def test_dashboard_reads_unconfirmed_update_result(tmp_path, monkeypatch):
    control, _ = controller(tmp_path, monkeypatch)
    report = {"success": False, "status": "failed", "outcome_unknown": True,
              "attempt_directory": str(tmp_path.parent / ".install.auto-update-attempt")}
    (tmp_path / "auto-update-desktop.json").write_text(json.dumps(report), encoding="utf-8")
    assert control.status(check=False)["report"] == report


def test_dashboard_refuses_config_outside_running_environment(tmp_path, monkeypatch):
    control, _ = controller(tmp_path, monkeypatch)
    other = updates.DashboardUpdates(str(tmp_path / "other.toml"))
    assert control.status(check=False)["eligible"]
    assert not other.status()["eligible"]
    with pytest.raises(ValueError, match="managed"):
        other.install(VERSION, REVISION)


@pytest.mark.parametrize(("peer", "origin", "confirmed", "expected"), [
    ("192.0.2.1", "http://127.0.0.1:11435", True, 403),
    ("127.0.0.1", "https://example.invalid", True, 403),
    ("127.0.0.1", "http://127.0.0.1:11435", False, 400),
    ("127.0.0.1", "http://127.0.0.1:11435", True, 202),
])
def test_update_post_enforces_http_boundary(monkeypatch, peer, origin, confirmed, expected):
    launched = []
    controller = SimpleNamespace(install=lambda version, revision: launched.append((version, revision)) or {"success": True})
    telemetry = SimpleNamespace(record_system=lambda *args, **kwargs: True)
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"server": {"bind": "127.0.0.1", "port": 11435}}, dashboard_updates=controller, telemetry=telemetry,
    ))
    handler = object.__new__(http_server.Handler)
    handler.path, handler.command, handler.client_address = "/api/updates", "POST", (peer, 10000)
    handler.server = SimpleNamespace()
    handler.headers = {"Host": "127.0.0.1:11435", "Origin": origin,
                       "X-LocalAI-Client": "dashboard", "Sec-Fetch-Site": "same-origin"}
    handler._read_json = lambda: {"action": "install", "version": VERSION, "revision": REVISION, "confirm_restart": confirmed}
    codes = []
    handler._send = lambda status, payload: codes.append(status)
    handler.do_POST()
    assert codes == [expected]
    assert launched == ([(VERSION, REVISION)] if expected == 202 else [])


@pytest.mark.parametrize(("peer", "origin", "fetch", "confirmed", "expected"), [
    ("192.0.2.1", "", "", True, 403),
    ("127.0.0.1", "http://127.0.0.1:11435", "", True, 403),
    ("127.0.0.1", "", "same-origin", True, 403),
    ("127.0.0.1", "", "", False, 400),
    ("127.0.0.1", "", "", True, 202),
])
def test_native_update_boundary(monkeypatch, peer, origin, fetch, confirmed, expected):
    launched = []
    control = SimpleNamespace(install=lambda version, revision: launched.append((version, revision)) or {"success": True})
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"server": {"bind": "127.0.0.1", "port": 11435}},
        dashboard_updates=control, telemetry=SimpleNamespace(record_system=lambda *a, **k: True),
    ))
    handler = object.__new__(http_server.Handler)
    handler.path, handler.command, handler.client_address = "/api/updates", "POST", (peer, 10000)
    handler.server = SimpleNamespace()
    handler.headers = {"Host": "127.0.0.1:11435", "Origin": origin, "X-LocalAI-Client": "desktop",
                       "Sec-Fetch-Site": fetch}
    handler._read_json = lambda: {"action": "install", "version": VERSION, "revision": REVISION, "confirm_restart": confirmed}
    codes = []
    handler._send = lambda status, payload: codes.append(status)
    handler.do_POST()
    assert codes == [expected]
    assert launched == ([(VERSION, REVISION)] if expected == 202 else [])
