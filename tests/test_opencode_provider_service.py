from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import urllib.request
import urllib.error

import pytest

from local_ai_hub.opencode_provider_service import ProviderService, derive_provider_token
from local_ai_hub.scheduler import AffinityScheduler


@pytest.fixture(autouse=True)
def model_preflight(monkeypatch):
    monkeypatch.setattr("local_ai_hub.opencode_models.local_inventory", lambda _: {"model-a"})
    monkeypatch.setattr("local_ai_hub.opencode_models.local_loaded_models", lambda _: set())
    monkeypatch.setattr("local_ai_hub.opencode_models.require_local_source_version", lambda _: None)


@pytest.fixture
def scheduler(tmp_path):
    result = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    yield result
    result.close()


def test_service_rejects_other_resident_model_and_releases_reservation(scheduler, monkeypatch):
    def loaded(origin):
        assert scheduler.foreground_busy()
        return {"different-model"}
    monkeypatch.setattr("local_ai_hub.opencode_models.local_loaded_models", loaded)
    service = ProviderService(scheduler, upstream_url="http://127.0.0.1:11434", hub_token="x" * 40)
    with pytest.raises(RuntimeError, match="another model"):
        service.start("model-a")
    assert service.status()["state"] == "stopped"
    assert not scheduler.foreground_busy()


def test_service_inventory_unavailable_releases_reservation(scheduler, monkeypatch):
    from local_ai_hub.opencode_models import ModelPreparationError
    def unavailable(origin):
        assert scheduler.foreground_busy()
        raise ModelPreparationError("inventory unavailable")
    monkeypatch.setattr("local_ai_hub.opencode_models.local_inventory", unavailable)
    service = ProviderService(scheduler, upstream_url="http://127.0.0.1:11434", hub_token="x" * 40)
    with pytest.raises(RuntimeError, match="inventory unavailable"):
        service.start("model-a")
    assert not scheduler.foreground_busy()


def test_unverified_version_never_reserves_gpu(scheduler, monkeypatch):
    from local_ai_hub.opencode_models import ModelPreparationError
    def unsupported(origin):
        raise ModelPreparationError("Ollama version is not verified")
    monkeypatch.setattr("local_ai_hub.opencode_models.require_local_source_version", unsupported)
    service = ProviderService(scheduler, upstream_url="http://127.0.0.1:11434", hub_token="x" * 40)
    with pytest.raises(ModelPreparationError, match="version"):
        service.start("model-a")
    assert service.status()["state"] == "stopped"
    assert not scheduler.foreground_busy()


def test_service_checks_real_loopback_inventory_before_start(scheduler, monkeypatch):
    from local_ai_hub import opencode_models
    monkeypatch.setattr(opencode_models, "local_inventory", lambda origin: opencode_models._local_models(origin, "/api/tags"))
    monkeypatch.setattr(opencode_models, "local_loaded_models", lambda origin: opencode_models._local_models(origin, "/api/ps"))
    seen = []
    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(200)
            self.end_headers()
            name = "model-a" if self.path == "/api/tags" else "other-model"
            self.wfile.write(json.dumps({"models": [{"name": name}]}).encode())
        def log_message(self, *args):
            pass
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    try:
        service = ProviderService(scheduler, upstream_url=f"http://127.0.0.1:{backend.server_port}", hub_token="x" * 40)
        with pytest.raises(RuntimeError, match="another model"):
            service.start("model-a")
        assert seen == ["/api/tags", "/api/ps"]
        assert not scheduler.foreground_busy()
    finally:
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=3)


def test_provider_service_starts_and_closes_without_disclosing_secret(scheduler):
    token_val = "test-token-" + "x" * 40
    service = ProviderService(scheduler, upstream_url="http://127.0.0.1:11434", hub_token=token_val)
    started = service.start("model-a")
    assert started["port"] > 0
    assert started["model"] == "model-a"
    assert token_val not in str(started)
    token = derive_provider_token(token_val, started["nonce"])
    assert len(token) >= 32 and token not in str(started)
    assert scheduler.foreground_busy()
    status = service.status()
    assert status["state"] == "running" and status["nonce"] == started["nonce"]
    with pytest.raises(RuntimeError):
        service.start("model-a")
    service.close()
    assert not scheduler.foreground_busy()
    service.close()


def test_request_stop_is_nonblocking_and_reports_completion(scheduler):
    service = ProviderService(scheduler, upstream_url="http://127.0.0.1:11434", hub_token="x" * 40)
    service.start("model-a")
    done = service.request_stop()
    assert done.wait(timeout=3)
    assert service.status()["state"] == "stopped"
    assert not scheduler.foreground_busy()
    service.close()


@pytest.mark.parametrize("url", ["https://127.0.0.1:11434", "http://localhost:11434", "http://127.0.0.1:11434/path", "http://example.com:11434", "http://user@127.0.0.1:11434"])
def test_service_rejects_noncanonical_upstream_before_reserving(scheduler, url):
    service = ProviderService(scheduler, upstream_url=url, hub_token="x" * 40)
    with pytest.raises(ValueError):
        service.start("model-a")
    assert not scheduler.foreground_busy()


def test_service_requires_configured_secret_before_reserving(scheduler):
    for secret in ("", "short", "x" * 31, None):
        service = ProviderService(scheduler, upstream_url="http://127.0.0.1:11434", hub_token=secret)
        with pytest.raises(ValueError):
            service.start("model-a")
        assert not scheduler.foreground_busy()


def test_app_owns_provider_lifecycle_without_starting_it(tmp_path):
    from local_ai_hub.app import LocalAIApp

    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\nauto_start_ollama = false\n'
        '[ollama]\nenabled = false\n[llama_cpp]\nmode = "off"\n'
        '[background_gpu]\nenabled = false\n[preprocessing]\nenabled = false\n', encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    assert app.opencode_provider._server is None
    app.close(timeout=10)
    assert app.close_report["components"]["opencode_provider"]["state"] == "completed"


def test_uncertain_stream_prevents_service_stop_from_releasing_fence(scheduler):
    class Backend(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_GET(self):
            data = b'{"version":"0.34.0"}' if self.path == "/api/version" else b'{"models":[]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[]}\n\n')
        def log_message(self, *args):
            pass
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    secret = "x" * 40
    service = ProviderService(scheduler, upstream_url=f"http://127.0.0.1:{backend.server_port}", hub_token=secret, peer_verifier=lambda sock: None)
    try:
        info = service.start("model-a")
        token = derive_provider_token(secret, info["nonce"])
        request = urllib.request.Request(f'http://127.0.0.1:{info["port"]}/v1/chat/completions',
            data=json.dumps({"model": "model-a", "stream": True}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
        with pytest.raises(RuntimeError, match="did not confirm safe GPU release"):
            service.stop()
        assert scheduler.foreground_busy()
    finally:
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=3)


def test_stop_waits_for_active_response_before_releasing_fence(scheduler):
    entered, release = threading.Event(), threading.Event()
    class Backend(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_GET(self):
            data = b'{"version":"0.34.0"}' if self.path == "/api/version" else b'{"models":[]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            entered.set()
            release.wait(timeout=5)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[]}\n\ndata: [DONE]\n\n')
        def log_message(self, *args):
            pass
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    service = ProviderService(scheduler, upstream_url=f"http://127.0.0.1:{backend.server_port}", hub_token="x" * 40, peer_verifier=lambda sock: None)
    info = service.start("model-a")
    token = derive_provider_token("x" * 40, info["nonce"])
    response = []
    def fetch():
        request = urllib.request.Request(f'http://127.0.0.1:{info["port"]}/v1/chat/completions',
            data=json.dumps({"model": "model-a", "stream": True}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as result:
            response.append(result.read())
    client = threading.Thread(target=fetch)
    client.start()
    assert entered.wait(timeout=3)
    stopper = threading.Thread(target=service.stop)
    stopper.start()
    try:
        assert scheduler.foreground_busy()
        assert stopper.is_alive()
    finally:
        release.set()
        client.join(timeout=5)
        stopper.join(timeout=5)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=3)
    assert not client.is_alive() and not stopper.is_alive()
    assert response[0].endswith(b"data: [DONE]\n\n")
    assert not scheduler.foreground_busy()


def test_http_lifecycle_requires_hub_token_and_never_returns_provider_secret(tmp_path, monkeypatch):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    secret = "x" * 40
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\nollama_url = "http://127.0.0.1:11434"\nauto_start_ollama = false\n'
        f'[security]\napi_token = "{secret}"\n[ollama]\nenabled = false\n[llama_cpp]\nmode = "off"\n'
        '[background_gpu]\nenabled = false\n[preprocessing]\nenabled = false\n', encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def post(path, body, token, actor="opencode-local"):
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-LocalAI-Token": token, "X-LocalAI-Agent": actor}, method="POST")
        return urllib.request.urlopen(request, timeout=5)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            post("/api/opencode/provider/start", {"model": "model-a"}, "wrong")
        assert error.value.code == 401
        error.value.close()
        with post("/api/opencode/provider/start", {"model": "model-a"}, secret) as response:
            started = json.load(response)
        assert started["success"] and secret not in str(started)
        derived = derive_provider_token(secret, started["nonce"])
        assert derived not in str(started)
        with pytest.raises(urllib.error.HTTPError) as duplicate:
            post("/api/opencode/provider/start", {"model": "other-model"}, secret)
        assert duplicate.value.code == 409
        duplicate.value.close()
        with post("/api/opencode/provider/status", {}, secret) as response:
            status = json.load(response)
        assert status["state"] == "running" and status["nonce"] == started["nonce"]
        with pytest.raises(urllib.error.HTTPError) as gaming:
            post("/api/admin/mode", {"mode": "gaming"}, secret, actor="generic")
        assert gaming.value.code == 409
        assert json.loads(gaming.value.read())["error_code"] == "opencode_provider_not_stopped"
        gaming.value.close()
        assert app.opencode_provider._stopped.wait(timeout=5)
        assert not app.scheduler.foreground_busy()
        with post("/api/opencode/provider/start", {"model": "model-a"}, secret) as response:
            restarted = json.load(response)
        assert restarted["success"]
        with pytest.raises(urllib.error.HTTPError) as stale:
            post("/api/opencode/provider/stop", {"nonce": started["nonce"]}, secret)
        assert stale.value.code == 409
        stale.value.close()
        assert app.opencode_provider.status()["state"] == "running"
        with post("/api/opencode/provider/stop", {"nonce": restarted["nonce"]}, secret) as response:
            assert json.load(response)["state"] == "stopping"
        with post("/api/opencode/provider/wait", {"timeout_seconds": 5}, secret) as response:
            assert json.load(response)["state"] == "stopped"
        assert not app.scheduler.foreground_busy()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close(timeout=10)


def test_lifecycle_obeys_hub_operational_mode_and_admin_authorization():
    from local_ai_hub.http_server import _http_admin_action, _http_mode_policy
    start = "/api/opencode/provider/start"
    status = "/api/opencode/provider/status"
    stop = "/api/opencode/provider/stop"
    wait = "/api/opencode/provider/wait"
    assert _http_mode_policy("POST", start) == "blocked"
    assert _http_mode_policy("POST", status) == "operator"
    assert _http_mode_policy("POST", stop) == "operator"
    assert _http_mode_policy("POST", wait) == "operator"
    for path in (start, status, stop, wait):
        assert _http_admin_action("POST", path) == "model.manage"
