from unittest.mock import Mock

from local_ai_hub.agent_semaphores import SemaphoreStore
from local_ai_hub.client import HubClient


def test_client_forwards_optional_semaphore_ttl_without_coercion():
    client = object.__new__(HubClient)
    client.post = Mock(return_value={"success": True})

    client.coord(action="semaphore_acquire", name="demo", owner="owner", capacity=1,
                 ttl_seconds=None, timeout=0.0)

    assert client.post.call_args.args[1]["ttl_seconds"] is None


def test_store_no_expiry_and_explicit_expiry(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("local_ai_hub.agent_semaphores.time.time", lambda: now[0])
    store = SemaphoreStore(tmp_path / "semaphores.sqlite")
    permanent = store.acquire("permanent", owner="first", ttl_seconds=None)
    timed = store.acquire("timed", owner="first", ttl_seconds=10)
    assert permanent["expires_at"] is None
    assert timed["expires_at"] == 1010.0

    now[0] = 2000.0
    assert store.status("permanent")["semaphore"]["active_count"] == 1
    assert store.status("timed")["semaphore"]["active_count"] == 0
    assert store.acquire("permanent", owner="second", ttl_seconds=None)["acquired"] is False
    assert store.release("permanent", permanent["lease_id"], owner="first")["released"] is True


def test_explicit_ttl_reaches_client_transport():
    client = object.__new__(HubClient)
    client.post = Mock(return_value={"success": True})
    client.coord(action="semaphore_acquire", name="demo", owner="owner", capacity=1,
                 ttl_seconds=45, timeout=0.0)
    assert client.post.call_args.args[1]["ttl_seconds"] == 45


def test_nonfinite_ttl_is_rejected(tmp_path):
    import pytest

    store = SemaphoreStore(tmp_path / "semaphores.sqlite")
    for ttl in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError):
            store.acquire("invalid", owner="first", ttl_seconds=ttl)


def test_corrupt_expiry_does_not_become_unlimited(tmp_path):
    import sqlite3
    import pytest

    path = tmp_path / "semaphores.sqlite"
    store = SemaphoreStore(path)
    store.acquire("corrupt", owner="first", ttl_seconds=10)
    with sqlite3.connect(path) as con:
        con.execute("UPDATE agent_semaphores SET holders_json = ? WHERE name = ?",
                    ('[{"owner":"first","expires_at":Infinity}]', "corrupt"))
    con.close()
    with pytest.raises(ValueError):
        store.status("corrupt")


def test_optional_ttl_through_loopback_http(tmp_path, monkeypatch):
    import threading
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[agent_state]\nenabled = true\n[security]\n'
        f'allowed_roots = ["{tmp_path.as_posix()}"]\n', encoding="utf-8"
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = HubClient(config_path=str(config), auto_start=False)
    try:
        result = client.coord(action="semaphore_acquire", name="http-test",
                              owner="test-owner", ttl_seconds=None)
        assert result["success"] is True and result["acquired"] is True
        assert result["expires_at"] is None
        status = client.coord(action="semaphore_status", name="http-test")
        assert status["semaphore"]["active_count"] == 1
        released = client.coord(action="semaphore_release", name="http-test",
                                owner="test-owner", lease_id=result["lease_id"])
        assert released["released"] is True
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()
