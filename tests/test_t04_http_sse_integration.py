from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from local_ai_hub import http_server
from local_ai_hub.client import HubClient


def _fixture(tmp_path, monkeypatch, *, token: str = "expected-local-token"):
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(config={"security": {"api_token": "expected-local-token"}}),
    )
    authorized: list[tuple[str, str, bool]] = []
    first_event = threading.Event()
    release = threading.Event()
    handler_done = threading.Event()

    class StreamHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            allowed = http_server.Handler._authorized(self)
            authorized.append((self.headers.get("X-LocalAI-Token", ""), self.headers.get("Authorization", ""), allowed))
            if not allowed:
                body = json.dumps({"success": False, "error": "unauthorized"}).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                handler_done.set()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(b'event: update\ndata: {"value":1}\n\n')
            self.wfile.flush()
            first_event.set()
            release.wait(3)
            try:
                self.wfile.write(b": fixture-release\n\n")
                self.wfile.flush()
            except OSError:
                pass
            finally:
                handler_done.set()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), StreamHandler)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    config = tmp_path / "client.toml"
    security = f"[security]\napi_token='{token}'\n" if token else ""
    config.write_text(
        f"[server]\nport={server.server_port}\nstate_dir='{(tmp_path / 'state').as_posix()}'\n"
        "[client]\nmax_request_timeout_seconds=5\n" + security,
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    return server, server_thread, client, authorized, first_event, release, handler_done


def _stop(server, server_thread, client, release, handler_done) -> None:
    release.set()
    handler_done.wait(1)
    client.close()
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=2)


def test_sse_http_fixture_rejects_missing_configured_auth_token(tmp_path, monkeypatch) -> None:
    server, server_thread, client, authorized, _first, release, done = _fixture(
        tmp_path, monkeypatch, token=""
    )
    events = client.stream_events(timeout=1)
    try:
        with pytest.raises(HTTPError) as error:
            next(events)
        assert error.value.code == 401
        assert authorized == [("", "", False)]
    finally:
        if "error" in locals():
            error.value.close()
        events.close()
        _stop(server, server_thread, client, release, done)
    assert done.is_set()


def test_sse_http_fixture_cancel_stops_real_client_stream_after_keepalive(tmp_path, monkeypatch) -> None:
    server, server_thread, client, authorized, first, release, done = _fixture(tmp_path, monkeypatch)
    cancel = threading.Event()
    events = client.stream_events(timeout=10, cancel_event=cancel)
    try:
        assert next(events) == ("update", {"value": 1})
        assert first.wait(1)
        worker_started = threading.Event()

        def read_next():
            worker_started.set()
            return next(events, None)

        started_at = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(read_next)
            assert worker_started.wait(1)
            time.sleep(0.05)
            cancel.set()
            release.set()
            assert pending.result(timeout=1) is None
        assert time.monotonic() - started_at < 0.75
        assert authorized == [("expected-local-token", "Bearer expected-local-token", True)]
        assert done.wait(1)
    finally:
        events.close()
        _stop(server, server_thread, client, release, done)


def test_sse_http_fixture_deadline_closes_response_and_reports_unknown_timeout(tmp_path, monkeypatch) -> None:
    server, server_thread, client, _authorized, first, release, _done = _fixture(tmp_path, monkeypatch)
    client.max_request_timeout = 0.2
    events = client.stream_events(timeout=0.1)
    try:
        assert next(events) == ("update", {"value": 1})
        assert first.wait(1)
        started_at = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(next, events, None).result(timeout=1)
        elapsed = time.monotonic() - started_at
        assert result[0] == "error"
        assert result[1]["retry_timeout"] is True
        assert result[1]["outcome_unknown"] is True
        assert elapsed < 0.75
    finally:
        events.close()
        _stop(server, server_thread, client, release, _done)
