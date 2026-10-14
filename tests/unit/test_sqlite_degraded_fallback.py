import http.client
import json
import logging
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock
from local_ai_hub import http_server
from local_ai_hub.http_server import Handler
from local_ai_hub.sqlite_support import retry_busy, with_degraded_fallback, connect_sqlite


class _LockedDatabase:
    def __init__(self, path):
        self.writer = sqlite3.connect(path, timeout=0, check_same_thread=False)
        self.reader = sqlite3.connect(path, timeout=0, check_same_thread=False)
        self.writer.execute("CREATE TABLE sample (value INTEGER)")
        self.writer.commit()
        self.writer.execute("BEGIN EXCLUSIVE")
        self.calls = 0

    def read(self):
        self.calls += 1
        return self.reader.execute("SELECT value FROM sample").fetchall()

    def close(self):
        self.reader.close()
        self.writer.rollback()
        self.writer.close()


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(Handler, "_require_authorized", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(http_server, "_http_mode_gate_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(Handler, "_tenant", lambda self: "test-tenant")

    server = http_server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    try:
        yield ("127.0.0.1", server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "HTTP server thread did not stop"


def _request(api, path, *, method="GET", payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    connection = http.client.HTTPConnection(*api, timeout=2)
    headers = {"Content-Type": "application/json"} if data is not None else {}
    try:
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()

def test_retry_busy_raises_on_persistent_lock_when_fallback_disabled():
    counter = {"calls": 0}
    def failing_op():
        counter["calls"] += 1
        raise sqlite3.OperationalError("database is locked")
    
    with pytest.raises(sqlite3.OperationalError):
        retry_busy(failing_op, retries=2, base_delay_seconds=0.001)
    assert counter["calls"] == 2

def test_retry_busy_returns_degraded_dict_when_fallback_enabled():
    counter = {"calls": 0}
    def failing_op():
        counter["calls"] += 1
        raise sqlite3.OperationalError("database is locked")
    
    result = retry_busy(failing_op, retries=3, base_delay_seconds=0.001, fallback_degraded=True)
    assert counter["calls"] == 3
    assert result == {
        "success": False,
        "degraded": True,
        "error": "database_locked",
        "error_code": "database_locked",
    }

def test_retry_busy_returns_custom_degraded_value():
    def failing_op():
        raise sqlite3.OperationalError("database table is busy")
    
    custom_fallback = {"items": [], "cached": True, "degraded": True}
    result = retry_busy(
        failing_op,
        retries=2,
        base_delay_seconds=0.001,
        fallback_degraded=True,
        degraded_value=custom_fallback,
    )
    assert result == custom_fallback

def test_with_degraded_fallback_convenience_function():
    def failing_op():
        raise sqlite3.OperationalError("database is locked")
    
    res = with_degraded_fallback(failing_op, retries=2, base_delay_seconds=0.001)
    assert res["success"] is False
    assert res["degraded"] is True
    assert res["error"] == "database_locked"

def test_with_degraded_fallback_succeeds_when_operation_succeeds():
    assert with_degraded_fallback(lambda: {"data": 42}) == {"data": 42}


@pytest.mark.parametrize(
    ("method", "path", "install_operation"),
    [
        ("GET", "/api/live/status", "realtime_status"),
        ("POST", "/api/async-jobs", "async_submit"),
    ],
)
def test_locked_sqlite_retries_degrade_at_real_http_boundary(
    api, monkeypatch, tmp_path, method, path, install_operation
):
    database = _LockedDatabase(tmp_path / "locked.sqlite")

    def exhausted_read():
        return retry_busy(database.read, retries=2, base_delay_seconds=0, jitter=False)

    side_effect = tmp_path / "post-side-effect.txt"

    def submit_with_side_effect(*_args):
        side_effect.write_text("owned test side effect", encoding="utf-8")
        return exhausted_read()

    app = SimpleNamespace(
        logger=logging.getLogger("task14-test"),
        config={"monitoring": {"live_max_batch": 200}},
        realtime_status=lambda **_kwargs: exhausted_read(),
        async_jobs=SimpleNamespace(submit=submit_with_side_effect),
    )
    monkeypatch.setattr(http_server, "APP", app)
    try:
        if install_operation == "realtime_status":
            status, body = _request(api, path)
        else:
            status, body = _request(
                api, path, method="POST", payload={"action": "submit", "job_action": "reason"}
            )

        assert status == 503
        assert body["success"] is False
        assert body["degraded"] is True
        assert body["error"] == "database_locked"
        assert body["error_code"] == "database_locked"
        if method == "GET":
            assert body["retryable"] is True
            assert body["terminal"] is False
            assert body["outcome_unknown"] is False
        else:
            assert body["retryable"] is False
            assert body["terminal"] is True
            assert body["outcome_unknown"] is True
            assert side_effect.read_text(encoding="utf-8") == "owned test side effect"
        assert database.calls == 2
    finally:
        database.close()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_nonbusy_sqlite_error_keeps_internal_error_response(api, monkeypatch, method):
    def fail():
        raise sqlite3.OperationalError("no such table: sample")

    app = SimpleNamespace(
        logger=logging.getLogger("task14-test"),
        config={"monitoring": {"live_max_batch": 200}},
        realtime_status=lambda **_kwargs: retry_busy(fail, retries=2, base_delay_seconds=0),
        async_jobs=SimpleNamespace(
            submit=lambda *_args: retry_busy(fail, retries=2, base_delay_seconds=0)
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)

    if method == "GET":
        status, body = _request(api, "/api/live/status")
    else:
        status, body = _request(
            api,
            "/api/async-jobs",
            method="POST",
            payload={"action": "submit", "job_action": "reason"},
        )

    assert status == 500
    assert body["success"] is False
    assert body["error_code"] == "internal_error"


def test_retry_busy_preserves_success_value_and_original_exhausted_error():
    marker = object()
    assert retry_busy(lambda: marker) is marker

    error = sqlite3.OperationalError("database is locked")

    def fail():
        raise error

    with pytest.raises(sqlite3.OperationalError) as caught:
        retry_busy(fail, retries=1, base_delay_seconds=0)
    assert caught.value is error
