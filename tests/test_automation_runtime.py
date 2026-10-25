"""Opt-in actual headless Chrome test; never attaches to a personal profile."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.automation_service import create_automation_broker


@pytest.mark.skipif(not os.environ.get("LOCAL_AI_AUTOMATION_MCP_CLI"), reason="explicit installed Playwright MCP CLI required")
def test_actual_isolated_chrome_actions_and_policy(tmp_path):
    visits = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            visits.append(self.path)
            if self.path == "/app/redirect":
                self.send_response(302)
                self.send_header("Location", "/outside")
                self.end_headers()
                return
            if self.path == "/app/download":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="fixture.txt"')
                self.end_headers()
                self.wfile.write(b"Owned download proof")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b'<html><title>Owned fixture</title><body><label>Name<input id="name"></label>'
                             b'<button id="go" onclick="document.querySelector(\'#result\').textContent=document.querySelector(\'#name\').value">Apply</button>'
                             b'<p id="result">Initial</p><input id="file" type="file">'
                             b'<a id="download" href="/app/download" download>Download</a>'
                             b'<button id="confirm" onclick="document.querySelector(\'#result\').textContent=confirm(\'Continue?\')?\'Accepted\':\'Declined\'">Confirm</button>'
                             b'<iframe src="/outside"></iframe></body></html>')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/app"
    upload = tmp_path / "upload"
    upload.mkdir()
    file = upload / "fixture.txt"
    file.write_text("Owned upload proof", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path)}, "automation": {
        "enabled": True, "allowed_targets": [url], "timeout_seconds": 30,
        "allowed_file_roots": [str(upload)],
        "playwright_command": [os.environ.get("LOCAL_AI_AUTOMATION_NODE", "C:/Program Files/nodejs/node.exe"),
                               os.environ["LOCAL_AI_AUTOMATION_MCP_CLI"]]}}
    broker = create_automation_broker(config, ArtifactStore(tmp_path))
    def call(request):
        return broker.execute(root=str(tmp_path), task_id="runtime", request=request)
    try:
        opened = call({"op": "open", "mode": "isolated", "url": url})
        assert opened["success"], opened
        session = opened["automation"]
        diagnostics = []
        transport = broker.sessions[session["session_id"]].backend.transport
        original_call = transport.call
        def traced_call(code, timeout):
            try:
                return original_call(code, timeout)
            except Exception as exc:
                diagnostics.append(str(exc)[:1500])
                raise
        transport.call = traced_call
        count = 0
        def act(command, **fields):
            nonlocal count
            count += 1
            return call({"op": "act", "session_id": session["session_id"], "session_key": session["session_key"],
                         "request_id": f"request-{count}", "command": command, **fields})
        result = act("snapshot")
        assert result["success"], result
        assert result["automation"]["title"] == "Owned fixture"
        assert act("fill", selector="#name", text="Real Chrome proof")["success"]
        assert act("click", selector="#go")["success"]
        assert "Real Chrome proof" in json.dumps(act("snapshot"))
        screenshot = act("screenshot")
        assert screenshot["success"], screenshot
        assert screenshot["automation"]["artifact_id"].startswith("art_")
        assert screenshot["automation"]["size_bytes"] > 100
        assert act("upload", selector="#file", files=[str(file)])["success"]
        downloaded = act("download", selector="#download")
        assert downloaded["success"], downloaded
        assert downloaded["automation"]["mime_type"] == "application/octet-stream"
        assert downloaded["automation"]["size_bytes"] == len(b"Owned download proof")
        assert act("dialog", accept=True)["success"]
        confirmed = act("click", selector="#confirm")
        assert confirmed["success"], (confirmed, diagnostics)
        assert "Accepted" in json.dumps(act("snapshot"))
        new_tab = act("new_tab", url=url + "/two")
        assert new_tab["success"], new_tab
        assert "Accepted" not in json.dumps(act("snapshot"))
        assert act("close_tab")["success"]
        assert "Accepted" in json.dumps(act("snapshot"))
        assert "/outside" not in visits
        denied = act("navigate", url=url.rsplit("/", 1)[0] + "/outside")
        assert denied["error_code"] == "target_denied"
        redirected = act("navigate", url=url + "/redirect")
        assert redirected["success"] is False
        assert "/outside" not in visits
        second = call({"op": "open", "mode": "isolated", "url": url})["automation"]
        operation = {"op": "act", "session_id": second["session_id"], "session_key": second["session_key"],
                     "request_id": "cancelled-click", "command": "click", "selector": "#never-exists"}
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(call(operation)))
        worker.start()
        deadline = time.monotonic() + 10
        transport = broker.sessions[second["session_id"]].backend.transport
        while transport._future is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert transport._future is not None
        closing = call({"op": "close", "session_id": second["session_id"], "session_key": second["session_key"]})
        assert closing.get("cancel_requested") is True, closing
        worker.join(10)
        assert not worker.is_alive()
        assert outcome[0]["outcome_unknown"] is True
        assert second["session_id"] not in broker.sessions
    finally:
        broker.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.mark.skipif(not os.environ.get("LOCAL_AI_AUTOMATION_MCP_CLI"), reason="explicit installed Playwright MCP CLI required")
@pytest.mark.parametrize("declared_length", [True, False])
def test_actual_download_limit_stops_transfer_before_complete(tmp_path, declared_length):
    sent = []
    finished = threading.Event()
    total = 1024 * 1024

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path == "/app/file":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="large.bin"')
                if declared_length:
                    self.send_header("Content-Length", str(total))
                self.end_headers()
                try:
                    for _ in range(total // 4096):
                        self.wfile.write(b"x" * 4096)
                        self.wfile.flush()
                        sent.append(4096)
                        time.sleep(0.01)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                finally:
                    finished.set()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b'<a id="file" href="/app/file" download>Download</a>')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/app"
    store = ArtifactStore(tmp_path)
    broker = create_automation_broker({"server": {"state_dir": str(tmp_path)}, "automation": {
        "enabled": True, "allowed_targets": [url], "max_binary_bytes": 1024, "timeout_seconds": 15,
        "playwright_command": [os.environ.get("LOCAL_AI_AUTOMATION_NODE", "C:/Program Files/nodejs/node.exe"),
                               os.environ["LOCAL_AI_AUTOMATION_MCP_CLI"]]}}, store)
    try:
        opened = broker.execute(root=str(tmp_path), task_id="bounded-download", request={"op": "open", "mode": "isolated", "url": url})
        assert opened["success"], opened
        session = opened["automation"]
        result = broker.execute(root=str(tmp_path), task_id="bounded-download", request={
            "op": "act", "session_id": session["session_id"], "session_key": session["session_key"],
            "request_id": "large-download", "command": "download", "selector": "#file"})
        assert result.get("error_code") == "download_size_limit", result
        assert finished.wait(3), "producer connection was not cancelled"
        assert sum(sent) < total, "oversized transfer completed before rejection"
        assert not list((tmp_path / "automation").rglob("*.bin")), "rejected download left a file"
    finally:
        broker.close()
        server.shutdown()
        server.server_close()
        thread.join(3)
