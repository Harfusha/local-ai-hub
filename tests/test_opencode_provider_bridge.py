import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from local_ai_hub.opencode_inference_session import InferenceSessionError
from local_ai_hub.opencode_provider_bridge import ProviderBridge
from local_ai_hub.scheduler import AffinityScheduler


@pytest.fixture
def bridge(tmp_path):
    calls = []
    behavior = {"body": b'data: {"choices":[]}\n\ndata: [DONE]\n\n', "status": 200}
    class Backend(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_GET(self):
            assert self.path in {"/api/ps", "/api/version"}
            behavior.setdefault("connections", []).append((self.path, self.client_address))
            data = {"version": behavior.get("version", "0.34.0")} if self.path == "/api/version" else {"models": [{"name": name} for name in behavior.get("loaded", [])]}
            encoded = json.dumps(data).encode()
            self.send_response(behavior.get("inventory_status", 200))
            self.send_header("Content-Length", str(len(encoded)))
            if self.path == "/api/version" and behavior.get("close_after_version"):
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(encoded)
        def do_POST(self):
            behavior.setdefault("connections", []).append((self.path, self.client_address))
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append((self.path, json.loads(body)))
            if behavior.get("remote_alias"):
                if not calls[-1][1]["model"].endswith(":local"):
                    behavior["remote_calls"] = behavior.get("remote_calls", 0) + 1
                self.send_response(404)
                self.end_headers()
                return
            if "entered" in behavior:
                behavior["entered"].set()
                behavior["release"].wait(timeout=4)
            self.send_response(behavior["status"])
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            if "length" in behavior:
                self.send_header("Content-Length", str(behavior["length"]))
            self.end_headers()
            self.wfile.write(behavior["body"])
        def log_message(self, *args):
            pass
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    server = ProviderBridge(scheduler, "model-a", token="x" * 40, upstream_port=backend.server_port, peer_verifier=lambda sock: None)
    server.test_behavior = behavior
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, scheduler, calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    backend.shutdown()
    backend.server_close()
    backend_thread.join(timeout=3)
    scheduler.close()


def post(server, body, *, token="x" * 40, path="/v1/chat/completions"):
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST",
    )
    return urllib.request.urlopen(request, timeout=5)


@pytest.mark.parametrize("verifier", [None, lambda sock: (_ for _ in ()).throw(OSError("untrusted peer"))])
def test_unverified_peer_receives_no_http_request(bridge, verifier):
    server, scheduler, calls = bridge
    server.peer_verifier = verifier
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server, {"model": "model-a", "stream": True, "messages": [{"role": "user", "content": "secret"}]})
    assert error.value.code == 503
    error.value.close()
    assert calls == []
    assert server.test_behavior.get("connections", []) == []
    server.session.close()


def test_authenticated_single_model_stream_uses_real_loopback_backend(bridge):
    server, scheduler, calls = bridge
    with post(server, {"model": "model-a", "stream": True, "messages": []}) as response:
        assert response.status == 200
        assert response.read().endswith(b"data: [DONE]\n\n")
    assert calls == [("/v1/chat/completions", {"model": "model-a:local", "stream": True, "messages": []})]
    connections = server.test_behavior["connections"]
    assert [entry[0] for entry in connections] == ["/api/version", "/api/ps", "/v1/chat/completions"]
    assert len({entry[1] for entry in connections}) == 1
    assert scheduler.foreground_busy()
    server.session.close()


def test_rejects_new_resident_model_without_sending_inference(bridge):
    server, scheduler, calls = bridge
    with post(server, {"model": "model-a", "stream": True}) as response:
        assert response.read().endswith(b"data: [DONE]\n\n")
    assert len(calls) == 1
    server.test_behavior["loaded"] = ["different-model"]
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server, {"model": "model-a", "stream": True})
    assert error.value.code == 503
    error.value.close()
    assert len(calls) == 1
    assert scheduler.foreground_busy()
    server.session.close()


def test_unavailable_model_inventory_does_not_start_inference(bridge):
    server, scheduler, calls = bridge
    server.test_behavior["inventory_status"] = 503
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server, {"model": "model-a", "stream": True})
    assert error.value.code == 503
    error.value.close()
    assert calls == []
    assert scheduler.foreground_busy()
    server.session.close()


def test_unsupported_ollama_version_never_receives_inference(bridge):
    server, scheduler, calls = bridge
    server.test_behavior["version"] = "0.33.0"
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server, {"model": "model-a", "stream": True})
    assert error.value.code == 503
    error.value.close()
    assert calls == []
    server.session.close()


def test_closed_preflight_connection_is_not_replaced_for_inference(bridge):
    server, scheduler, calls = bridge
    server.test_behavior["close_after_version"] = True
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server, {"model": "model-a", "stream": True})
    assert error.value.code == 503
    error.value.close()
    assert calls == []
    assert scheduler.foreground_busy()
    server.session.close()


def test_renamed_remote_alias_is_sent_with_local_source_constraint(bridge):
    server, scheduler, calls = bridge
    server.test_behavior["remote_alias"] = True
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server, {"model": "model-a", "stream": True})
    assert error.value.code == 503
    error.value.close()
    assert calls[0][1]["model"] == "model-a:local"
    assert server.test_behavior.get("remote_calls", 0) == 0
    # Upstream failure cannot prove inference stopped, so the fence remains.
    with pytest.raises(InferenceSessionError):
        server.session.close()
    assert scheduler.foreground_busy()


def test_truncated_backend_stream_keeps_gpu_fenced(bridge):
    server, scheduler, calls = bridge
    server.test_behavior["body"] = b'data: {"choices":[]}\n\n'
    with post(server, {"model": "model-a", "stream": True}) as response:
        assert response.read() == server.test_behavior["body"]
    assert len(calls) == 1
    with pytest.raises(InferenceSessionError):
        server.session.close()
    assert scheduler.foreground_busy()


def test_backend_error_keeps_gpu_fenced(bridge):
    server, scheduler, _ = bridge
    server.test_behavior["status"] = 503
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server, {"model": "model-a", "stream": True})
    assert error.value.code == 503
    error.value.close()
    with pytest.raises(InferenceSessionError):
        server.session.close()
    assert scheduler.foreground_busy()


def test_done_in_shorter_than_declared_response_keeps_gpu_fenced(bridge):
    server, scheduler, _ = bridge
    server.test_behavior["length"] = len(server.test_behavior["body"]) + 100
    with post(server, {"model": "model-a", "stream": True}) as response:
        assert response.read().endswith(b"data: [DONE]\n\n")
    with pytest.raises(InferenceSessionError):
        server.session.close()
    assert scheduler.foreground_busy()


def test_second_request_is_rejected_while_first_is_running(bridge):
    server, _, calls = bridge
    server.test_behavior["entered"] = threading.Event()
    server.test_behavior["release"] = threading.Event()
    result = []
    def run():
        with post(server, {"model": "model-a", "stream": True}) as response:
            result.append(response.read())
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert server.test_behavior["entered"].wait(timeout=3)
        with pytest.raises(urllib.error.HTTPError) as rejected:
            post(server, {"model": "model-a", "stream": True})
        assert rejected.value.code == 503
        rejected.value.close()
    finally:
        server.test_behavior["release"].set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(calls) == 1 and result[0].endswith(b"data: [DONE]\n\n")
    server.session.close()


def test_duplicate_json_and_browser_origin_are_rejected(bridge):
    server, _, calls = bridge
    endpoint = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    for payload, headers, status in [
        (b'{"model":"model-a","model":"model-b","stream":true}', {}, 400),
        (b'{"model":"model-a","stream":true}', {"Origin": "https://example.com"}, 401),
    ]:
        request = urllib.request.Request(endpoint, data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + "x" * 40, **headers}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == status
        error.value.close()
    assert calls == []
    server.session.close()


@pytest.mark.parametrize("body,token,path,status", [
    ({"model": "model-a", "stream": True}, "wrong", "/v1/chat/completions", 401),
    ({"model": "model-b", "stream": True}, "x" * 40, "/v1/chat/completions", 400),
    ({"model": "model-a", "stream": False}, "x" * 40, "/v1/chat/completions", 400),
    ({"model": "model-a", "stream": True}, "x" * 40, "/v1/other", 404),
])
def test_bridge_rejects_unclassified_requests_before_backend(bridge, body, token, path, status):
    server, _, calls = bridge
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server, body, token=token, path=path)
    assert error.value.code == status
    error.value.close()
    assert calls == []
    server.session.close()
