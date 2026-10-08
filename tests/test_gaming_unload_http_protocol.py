import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from local_ai_hub.ollama import OllamaRuntime


def test_gaming_unload_uses_get_inventory_and_post_generate(tmp_path):
    models = ["unconfigured:latest", "other:latest"]
    calls = []

    class Backend(BaseHTTPRequestHandler):
        def reply(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            calls.append(("GET", self.path))
            assert self.path == "/api/ps"
            self.reply(200, {"models": [{"name": name} for name in models]})

        def do_POST(self):
            calls.append(("POST", self.path))
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if self.path != "/api/generate":
                self.reply(405, {"error": "method not allowed"})
                return
            assert payload["keep_alive"] == 0
            assert payload["prompt"] == ""
            models.remove(payload["model"])
            self.reply(200, {"done": True, "done_reason": "unload"})

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runtime = OllamaRuntime({
        "server": {"state_dir": str(tmp_path), "ollama_url": f"http://127.0.0.1:{server.server_port}"},
        "ollama": {"enabled": True, "request_attempts": 1},
        "llama_cpp": {"mode": "off", "models": {}},
    })
    try:
        result = runtime.unload_configured_models(timeout_seconds=2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)

    assert result["success"] is True
    assert result["verified"] is True
    assert models == []
    assert calls == [("GET", "/api/ps"), ("POST", "/api/generate"),
                     ("POST", "/api/generate"), ("GET", "/api/ps")]
