"""Fixture-only Ollama-shaped provider returning a fixed candidate patch.

This does not run a model and must never be used as model-quality evidence.
"""
import argparse
import difflib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--port", required=True, type=int)
args = parser.parse_args()
if not 1024 <= args.port <= 65535 or args.port in (11434, 11435, 11436, 61392):
    raise SystemExit("choose a separate non-production loopback port")
here = Path(__file__).resolve().parent
seed = (here / "workspace" / "repo" / "report.py").read_text(encoding="utf-8")
needle = '    args = parser.parse_args()\n    print(json.dumps({"greeting": f"Hello, {args.name}!"}, ensure_ascii=False, sort_keys=True))\n'
replacement = '''    parser.add_argument("--output")
    args = parser.parse_args()
    output = json.dumps({"greeting": f"Hello, {args.name}!"}, ensure_ascii=False, sort_keys=True) + "\\n"
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(output, encoding="utf-8")
    print(output, end="")
'''
if seed.count(needle) != 1:
    raise SystemExit("fixture seed does not match expected content")
candidate = seed.replace(needle, replacement)
patch = "".join(difflib.unified_diff(seed.splitlines(keepends=True), candidate.splitlines(keepends=True),
                                     fromfile="a/report.py", tofile="b/report.py"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, value):
        data = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self.reply({"models": [{"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 123,
                                     "digest": "synthetic-case-092", "details": {"family": "synthetic", "parameter_size": "7B"}}]})
        elif self.path == "/api/ps":
            self.reply({"models": []})
        else:
            self.reply({"version": "synthetic-case-092"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            self.send_error(413)
            return
        request = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/show":
            self.reply({"model_info": {"general.architecture": "synthetic", "llama.context_length": 8192},
                        "details": {"family": "synthetic", "parameter_size": "7B"}, "capabilities": ["completion"]})
            return
        if self.path not in {"/api/generate", "/api/chat"}:
            self.send_error(404)
            return
        request_text = json.dumps(request, ensure_ascii=False)
        is_plan = "PLAN A CODING WORK ORDER" in request_text
        is_review = "FINAL WHOLE-TASK VERIFIER" in request_text or "Verify this integrated change" in request_text
        plan = {"summary": "Add output option", "needs_agent": False, "question": "",
                "steps": [{"id": "s1", "kind": "edit", "task": "Add --output to report.py",
                           "depends_on": [], "acceptance": ["stdout remains unchanged"]},
                          {"id": "s2", "kind": "validate", "task": "Run the approved fixture oracle",
                           "depends_on": ["s1"], "acceptance": ["fixture oracle passes"]}],
                "validation_commands": ["python -m unittest oracle_092"]}
        # Never manufacture a positive semantic review or acceptance receipt.
        decline = {"passed": False, "summary": "synthetic backend cannot verify semantic correctness",
                   "criteria": [], "risks": ["synthetic provider"], "needs_agent": False}
        text = json.dumps(plan) if is_plan else json.dumps(decline) if is_review else patch
        with (here / "provider-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"path": self.path, "synthetic": True,
                                     "response": "fixed_plan" if is_plan else "review_declined" if is_review else "fixed_patch"}) + "\n")
        self.reply({"model": "qwen2.5-coder:7b", "response": text,
                    "message": {"role": "assistant", "content": text}, "done": True,
                    "prompt_eval_count": 1, "eval_count": 1})


ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
