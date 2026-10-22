"""HTTP test doubles must not inherit the installation's operational mode."""
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import http_server, operational_mode


def test_incomplete_http_stub_reads_test_state_not_installation(monkeypatch, tmp_path):
    security = {"allowed_roots": [str(tmp_path)]}
    config = {"security": security}
    app = SimpleNamespace(config=config)
    monkeypatch.setattr(http_server, "APP", app)
    seen = []
    load = operational_mode.load_operational_mode

    def observe(state_dir):
        seen.append(Path(state_dir))
        return load(state_dir)

    monkeypatch.setattr(http_server, "load_operational_mode", observe)
    assert http_server._http_mode_gate_error("POST", "/api/command", {}) is None
    assert seen == [tmp_path / "http-stub-state"]
    assert app.config is config
    assert app.config["security"] is security


def test_explicit_http_stub_gaming_state_remains_enforced(monkeypatch, tmp_path):
    state = tmp_path / "explicit-state"
    operational_mode.set_operational_mode(state, "gaming")
    config = {"server": {"state_dir": str(state)}}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config=config))
    result = http_server._http_mode_gate_error("POST", "/api/command", {})
    assert result["error_code"] == "operational_mode_blocked"
    assert result["operational_mode"] == "gaming"
    assert http_server.APP.config is config


def test_async_job_state_binding_is_preserved(monkeypatch, tmp_path):
    state = tmp_path / "jobs-state"
    operational_mode.set_operational_mode(state, "gaming")
    app = SimpleNamespace(config={}, async_jobs=SimpleNamespace(path=state / "jobs.sqlite3"))
    monkeypatch.setattr(http_server, "APP", app)
    result = http_server._http_mode_gate_error("POST", "/api/command", {})
    assert result["operational_mode"] == "gaming"
    assert app.config == {}


def test_explicit_invalid_state_is_not_replaced_by_fixture_default(monkeypatch):
    config = {"server": {"state_dir": None}}
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config=config))
    result = http_server._http_mode_gate_error("POST", "/api/command", {})
    assert result["success"] is False
    assert result["operational_mode"] == "maintenance"
    assert http_server.APP.config is config
