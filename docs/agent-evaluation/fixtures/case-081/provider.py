"""Deterministic Ollama-shaped provider: second marker fails; no model inference."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--port", required=True, type=int)
args = parser.parse_args()
if not 1024 <= args.port <= 65535 or args.port in (11434, 11435):
    raise SystemExit("unsafe provider port")
events = Path(__file__).resolve().parent / "provider-events.jsonl"

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, body, status=200):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self.send_json({"models": [{"name": "qwen2.5-coder:3b", "model": "qwen2.5-coder:3b", "size": 123, "digest": "synthetic-case-081", "details": {"family": "synthetic", "parameter_size": "3B"}}]})
        elif self.path == "/api/ps":
            self.send_json({"models": []})
        else:
            self.send_json({"version": "synthetic-case-081"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/api/show":
            self.send_json({"model_info": {"general.architecture": "synthetic", "llama.context_length": 8192}, "details": {"family": "synthetic", "parameter_size": "3B"}, "capabilities": ["completion"]})
            return
        payload = json.dumps(body, ensure_ascii=False)
        marker = next((name for name in ("CASE081_FIRST", "CASE081_FAIL", "CASE081_LAST") if name in payload), "unknown")
        with events.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"path": self.path, "marker": marker, "synthetic": True}) + "\n")
        if marker == "CASE081_FAIL":
            self.send_json({"error": "synthetic controlled failure"}, 400)
            return
        text = {"CASE081_FIRST": "První text: déšť naplnil nádrž.", "CASE081_LAST": "Třetí text: vítr zastavil provoz."}.get(marker, "Synthetic fixture response.")
        self.send_json({"model": "qwen2.5-coder:3b", "response": text, "message": {"role": "assistant", "content": text}, "done": True, "prompt_eval_count": 1, "eval_count": 1})

ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
