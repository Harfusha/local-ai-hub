from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub import http_server


def test_serve_closes_bound_server_and_app_when_telemetry_start_fails(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    config = {
        "server": {
            "state_dir": str(state_dir),
            "bind": "127.0.0.1",
            "port": 11435,
            "max_concurrent_requests": 4,
            "overload_wait_seconds": 0.05,
        },
        "security": {"rate_limit_requests": 600, "rate_limit_window_seconds": 60.0},
    }

    class Server:
        closed = False

        def configure_rate_limit(self, **_kwargs):
            pass

        def serve_forever(self):
            pytest.fail("serve_forever must not run after startup failure")

        def server_close(self):
            self.closed = True

    server = Server()

    def fail_session_start(*_args):
        raise RuntimeError("telemetry startup failed")

    app = SimpleNamespace(
        config=config,
        logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
        telemetry=SimpleNamespace(
            session_start=fail_session_start,
            session_stop=lambda: None,
            record_system=lambda *_args, **_kwargs: None,
            flush=lambda _timeout: None,
        ),
        closed=False,
    )
    app.close = lambda: setattr(app, "closed", True)

    monkeypatch.setattr(http_server, "APP", None)
    monkeypatch.setattr(http_server, "load_config", lambda _path: config)
    monkeypatch.setattr(http_server, "validate_network_security", lambda _config: None)
    monkeypatch.setattr(http_server, "_require_owned_supervisor_parent", lambda _state: None)
    monkeypatch.setattr(http_server, "LocalAIHTTPServer", lambda *_args, **_kwargs: server)
    monkeypatch.setattr(http_server, "LocalAIApp", lambda _path: app)

    with pytest.raises(RuntimeError, match="telemetry startup failed"):
        http_server.serve()

    assert server.closed is True
    assert app.closed is True
    assert http_server.APP is None
    assert not (state_dir / "hub.pid").exists()
