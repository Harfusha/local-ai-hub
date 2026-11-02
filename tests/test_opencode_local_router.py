import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from local_ai_hub.opencode_local_router import LocalRouter


@pytest.fixture
def endpoints():
    calls = []

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            calls.append((self.server.kind, self.path, self.headers.get("X-LocalAI-Token")))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append((self.server.kind, self.path, self.headers.get("Authorization"), body))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            self.wfile.write(b"data: second\n\n")

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), Endpoint) for _ in range(2)]
    for server, kind in zip(servers, ("hub", "provider")):
        server.kind = kind
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield servers, calls
    for server in servers:
        server.shutdown()
        server.server_close()


def test_routes_to_fixed_local_services_and_preserves_response(endpoints):
    servers, calls = endpoints
    with LocalRouter(servers[0].server_port, servers[1].server_port) as router:
        connection = http.client.HTTPConnection("127.0.0.1", router.port, timeout=3)
        connection.request("GET", "/health", headers={"X-LocalAI-Token": "restricted"})
        response = connection.getresponse()
        assert response.status == 200 and response.read() == b"ok"
        connection.request("POST", "/v1/chat/completions", body=b"{}", headers={"Authorization": "Bearer restricted"})
        response = connection.getresponse()
        assert response.status == 200 and response.read() == b"data: first\n\ndata: second\n\n"
    assert calls == [("hub", "/health", "restricted"), ("provider", "/v1/chat/completions", "Bearer restricted", b"{}")]


def test_restricted_status_route_is_exact(endpoints):
    servers, calls = endpoints
    with LocalRouter(servers[0].server_port, servers[1].server_port) as router:
        for path, expected in (("/api/live/status?light=1", 200),
                               ("/api/live/status", 403),
                               ("/api/live/status?light=1&detail=traces", 403),
                               ("/api/live/status?light=0", 403)):
            connection = http.client.HTTPConnection("127.0.0.1", router.port, timeout=3)
            connection.request("GET", path, headers={"X-LocalAI-Token": "restricted"})
            response = connection.getresponse()
            assert response.status == expected
            response.read()
    assert calls == [("hub", "/api/live/status?light=1", "restricted")]


@pytest.mark.parametrize("method,path", [("GET", "http://example.com/"), ("CONNECT", "example.com:443"),
                                       ("GET", "/api/opencode/provider/start"), ("POST", "/v1/models"),
                                       ("GET", "/health?other=true"), ("GET", "/%68ealth")])
def test_rejects_proxy_and_non_allowlisted_requests(endpoints, method, path):
    servers, calls = endpoints
    with LocalRouter(servers[0].server_port, servers[1].server_port) as router:
        connection = http.client.HTTPConnection("127.0.0.1", router.port, timeout=3)
        connection.request(method, path)
        response = connection.getresponse()
        assert 400 <= response.status < 500
        response.read()
    assert not calls


def test_rejects_untrusted_host_origin_and_ambiguous_framing(endpoints):
    servers, calls = endpoints
    with LocalRouter(servers[0].server_port, servers[1].server_port) as router:
        for headers in ({"Host": "evil.example"}, {"Origin": "http://evil.example"},
                        {"Transfer-Encoding": "chunked"}):
            connection = http.client.HTTPConnection("127.0.0.1", router.port, timeout=3)
            connection.request("POST", "/v1/chat/completions", body=b"{}", headers=headers)
            response = connection.getresponse()
            assert response.status == 400
            response.read()
    assert not calls


def test_registers_one_trusted_bridge_port_without_changing_targets(endpoints):
    servers, calls = endpoints
    with LocalRouter(servers[0].server_port, servers[1].server_port) as router:
        for invalid in (0, 65536, True, "1234"):
            with pytest.raises(ValueError):
                router.register_client_port(invalid)
        router.register_client_port(43210)
        with pytest.raises(RuntimeError):
            router.register_client_port(43211)
        for host, expected in (("127.0.0.1:43210", 200), ("127.0.0.1:43211", 400)):
            connection = http.client.HTTPConnection("127.0.0.1", router.port, timeout=3)
            connection.request("GET", "/health", headers={"Host": host})
            response = connection.getresponse()
            assert response.status == expected
            response.read()
    assert calls == [("hub", "/health", None)]


def test_sse_first_chunk_arrives_before_upstream_finishes(endpoints):
    servers, _ = endpoints
    released = threading.Event()

    class Streaming(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            if released.wait(4):
                self.wfile.write(b"data: second\n\n")
                self.wfile.flush()

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Streaming)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    try:
        with LocalRouter(servers[0].server_port, provider.server_port) as router:
            connection = http.client.HTTPConnection("127.0.0.1", router.port, timeout=3)
            connection.request("POST", "/v1/chat/completions", body=b"{}")
            response = connection.getresponse()
            assert response.readline() == b"data: first\n"
            released.set()
            assert b"data: second" in response.read()
    finally:
        released.set()
        provider.shutdown()
        provider.server_close()


@pytest.mark.parametrize("body", [b'{"action":"project_command"}', b'{"action":"receipt"}',
                                   b'{"action":"completion","action":"project_command"}', b'{bad json'])
def test_host_side_verification_execution_cannot_escape_sandbox(endpoints, body):
    servers, calls = endpoints
    with LocalRouter(servers[0].server_port, servers[1].server_port) as router:
        connection = http.client.HTTPConnection("127.0.0.1", router.port, timeout=3)
        connection.request("POST", "/api/agent-state/verification", body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        assert 400 <= response.status < 500
        response.read()
    assert not calls


def test_completion_check_is_forwarded_without_host_execution(endpoints):
    servers, calls = endpoints
    with LocalRouter(servers[0].server_port, servers[1].server_port) as router:
        connection = http.client.HTTPConnection("127.0.0.1", router.port, timeout=3)
        connection.request("POST", "/api/agent-state/verification", body=b'{"action":"completion"}')
        response = connection.getresponse()
        assert response.status == 200
        response.read()
    assert len(calls) == 1 and calls[0][0:2] == ("hub", "/api/agent-state/verification")
