from __future__ import annotations

import threading
import http.client
import os
import socket
import subprocess
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from local_ai_hub import browser_bridge
from local_ai_hub.artifacts import ArtifactStore


def test_browser_capture_artifacts_keep_full_dom_and_binary(tmp_path, monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"image payload"
    dom = "<html>" + "body" * 3000 + "</html>"

    class DummyBrowser:
        def __init__(self, **kwargs):
            assert str(tmp_path) in str(kwargs["scratch_dir"])

        def capture_page(self, url, **kwargs):
            return {"success": True, "url": url, "dom_snapshot": dom,
                    "screenshot_bytes": png, "title": "Page", "dom_truncated": False}

    monkeypatch.setattr(browser_bridge, "BrowserBridge", DummyBrowser)
    store = ArtifactStore(tmp_path)
    result = browser_bridge.capture_browser_page(
        "http://localhost:3000", artifacts=store, tenant="unit", state_dir=tmp_path,
    )
    assert result["success"]
    assert "screenshot_bytes" not in result
    assert len(result["dom_snapshot"]) <= 6000
    assert result["dom_preview_truncated"]
    assert store.get_binary(result["screenshot_artifact_id"], tenant="unit")["success"]
    assert store.get(result["dom_artifact_id"], tenant="unit", max_chars=len(dom) + 1)["text"] == dom


def test_browser_capacity_failure_releases_slot(tmp_path, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(browser_bridge.BrowserBridge, "_capture_slots", slots)

    def fail_temp(**kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(browser_bridge.tempfile, "mkdtemp", fail_temp)
    result = browser_bridge.BrowserBridge(executable="unused", scratch_dir=tmp_path).capture_page("http://localhost")
    assert result["success"] is False
    assert slots.acquire(blocking=False)
    slots.release()


def test_proxy_target_never_resolves_nonliteral_names():
    target = browser_bridge._LoopbackProxyHandler._target
    assert target("localhost", 3000) == ("127.0.0.1", 3000)
    assert target("::1", 443) == ("::1", 443)
    for host in ("localhost.evil.test", "169.254.169.254", "8.8.8.8", "example.com"):
        assert target(host, 80) is None


def test_proxy_rejects_zero_port_instead_of_retargeting_default():
    handler = browser_bridge._LoopbackProxyHandler.__new__(browser_bridge._LoopbackProxyHandler)
    assert handler._authority("127.0.0.1:0", 80) is None


def test_capture_backpressure_is_retryable_without_starting_browser(tmp_path, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(browser_bridge.BrowserBridge, "_capture_slots", slots)
    try:
        result = browser_bridge.BrowserBridge(executable="unused", scratch_dir=tmp_path).capture_page("http://localhost")
        assert result["error_code"] == "browser_busy"
        assert result["retryable"] and not result["terminal"]
        assert not list(tmp_path.iterdir())
    finally:
        slots.release()


@pytest.fixture
def proxy():
    server = browser_bridge._LoopbackProxy(("127.0.0.1", 0), browser_bridge._LoopbackProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("request_bytes", [
    b"GET http://169.254.169.254/secret HTTP/1.1\r\nHost: 169.254.169.254\r\n\r\n",
    b"CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8\r\n\r\n",
    b"GET http://localhost.evil.test/ HTTP/1.1\r\nHost: localhost.evil.test\r\n\r\n",
])
def test_proxy_denies_external_destinations_without_dns_or_connect(proxy, monkeypatch, request_bytes):
    def forbidden(*args, **kwargs):
        raise AssertionError("outbound connection attempted")

    monkeypatch.setattr(browser_bridge.socket, "create_connection", forbidden)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(proxy.server_address)
        client.sendall(request_bytes)
        assert b" 403 " in client.recv(4096).split(b"\r\n", 1)[0]


def test_proxy_forwards_local_response_and_blocks_redirect_destination(proxy):
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://203.0.113.5/private")
            self.end_headers()

        def log_message(self, *args):
            pass

    page = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    thread = threading.Thread(target=page.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(*proxy.server_address, timeout=3)
    try:
        connection.request("GET", f"http://127.0.0.1:{page.server_port}/")
        response = connection.getresponse()
        assert response.status == 302
        destination = response.getheader("Location")
        response.read()
        connection.close()
        connection.request("GET", destination)
        response = connection.getresponse()
        assert response.status == 403
        response.read()
    finally:
        connection.close()
        page.shutdown()
        page.server_close()
        thread.join(timeout=2)


def test_capture_stores_screenshot_reports_blocked_requests_and_cleans_scratch(tmp_path, monkeypatch):
    proxy_address = []

    def chrome(argv, **kwargs):
        assert kwargs["timeout"] == 20.0
        assert kwargs["max_output_bytes"] == browser_bridge.BrowserBridge.MAX_DOM_BYTES
        assert "--proxy-bypass-list=<-loopback>" in argv
        assert "--disable-quic" in argv
        assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in argv
        proxy_url = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--proxy-server="))
        from urllib.parse import urlsplit
        parsed = urlsplit(proxy_url)
        proxy_address.append((parsed.hostname, parsed.port))
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        try:
            connection.request("GET", "http://203.0.113.5/blocked")
            response = connection.getresponse()
            assert response.status == 403
            response.read()
        finally:
            connection.close()
        screenshot = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--screenshot="))
        Path(screenshot).write_bytes(b"\x89PNG\r\n\x1a\npixels")
        return subprocess.CompletedProcess(argv, 0, b"<html><title>Page</title></html>", b"")

    monkeypatch.setattr(browser_bridge, "run_hidden", chrome)
    result = browser_bridge.BrowserBridge(executable="unused", scratch_dir=tmp_path).capture_page("http://localhost:3000")
    assert result["success"]
    assert result["title"] == "Page"
    assert result["network_requests_denied"] == 1
    assert result["screenshot_bytes"].startswith(b"\x89PNG")
    assert not list(tmp_path.iterdir())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(1)
        assert client.connect_ex(proxy_address[0]) != 0


@pytest.mark.skipif(os.environ.get("LOCAL_AI_BROWSER_RUNTIME_TEST") != "1", reason="explicit installed-Chrome runtime acceptance")
def test_installed_chrome_captures_dom_png_and_blocks_external_subresource(tmp_path):
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            content = (b"<html><head><title>Hub capture acceptance</title></head>"
                       b"<body><h1>Current browser candidate</h1>"
                       b'<img src="http://203.0.113.5/blocked.png"></body></html>')
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    page = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    thread = threading.Thread(target=page.serve_forever, daemon=True)
    thread.start()
    store = ArtifactStore(tmp_path)
    try:
        result = browser_bridge.capture_browser_page(
            f"http://127.0.0.1:{page.server_port}/", artifacts=store, tenant="browser-runtime",
            state_dir=tmp_path, viewport={"width": 800, "height": 600},
        )
        diagnostic = (store.get(result["diagnostic_artifact_id"], tenant="browser-runtime")["text"]
                      if "diagnostic_artifact_id" in result else "")
        assert result["success"], (result, diagnostic)
        assert result["title"] == "Hub capture acceptance"
        assert "Current browser candidate" in result["dom_snapshot"]
        assert result["network_requests_denied"] >= 1
        assert store.get_binary(result["screenshot_artifact_id"], tenant="browser-runtime")["success"]
        assert not list((tmp_path / "browser-captures").iterdir())
    finally:
        page.shutdown()
        page.server_close()
        thread.join(timeout=2)
