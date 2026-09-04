from __future__ import annotations

import threading
import time

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def _client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n"
        "[client]\nmax_request_timeout_seconds=5\n",
        encoding="utf-8",
    )
    return HubClient(config_path=str(config), auto_start=False)


def test_client_reuses_one_http11_connection_for_sequential_requests(tmp_path, monkeypatch):
    class Response:
        status = 200
        reason = "OK"
        will_close = False
        headers = {}
        def read(self): return b'{"success":true}'

    class Connection:
        instances = []
        def __init__(self, *_args, **_kwargs): self.__class__.instances.append(self)
        def request(self, *_args, **_kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass

    monkeypatch.setattr(client_module.http.client, "HTTPConnection", Connection)
    client = _client(tmp_path)

    assert client.get("/health")["success"] is True
    assert client.get("/health")["success"] is True
    assert len(Connection.instances) == 1


def test_client_coalesces_simultaneous_identical_requests(tmp_path, monkeypatch):
    class Response:
        status = 200
        reason = "OK"
        will_close = False
        headers = {}
        def read(self): return b'{"success":true}'

    class Connection:
        calls = 0
        lock = threading.Lock()
        def __init__(self, *_args, **_kwargs): pass
        def request(self, *_args, **_kwargs):
            with self.lock: self.__class__.calls += 1
            time.sleep(0.05)
        def getresponse(self): return Response()
        def close(self): pass

    monkeypatch.setattr(client_module.http.client, "HTTPConnection", Connection)
    client = _client(tmp_path)
    start = threading.Barrier(2)
    results = []

    def call():
        start.wait()
        results.append(client.get("/health"))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(1)

    assert Connection.calls == 1
    assert sorted(bool(item.get("coalesced")) for item in results) == [False, True]
