"""Opt-in isolated Ollama test: no GPU model is loaded and no cloud is contacted."""
import json
import http.client
import os
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from local_ai_hub.process_utils import popen_managed, terminate_tree, process_owner_record
from local_ai_hub.opencode_peer import verify_supervised_peer
from local_ai_hub.opencode_provider_bridge import _preflight_connection


@pytest.mark.skipif(os.environ.get("LOCAL_AI_RUN_ISOLATED_OLLAMA_TEST") != "1" or not shutil.which("ollama"),
                    reason="explicit isolated Ollama test was not requested or Ollama is absent")
def test_real_ollama_local_suffix_rejects_renamed_remote_alias(tmp_path):
    remote_requests = []
    class Remote(BaseHTTPRequestHandler):
        def do_POST(self):
            remote_requests.append(self.path)
            self.send_response(503)
            self.end_headers()
        def log_message(self, *args):
            pass
    remote = ThreadingHTTPServer(("127.0.0.1", 0), Remote)
    remote_thread = threading.Thread(target=remote.serve_forever, daemon=True)
    remote_thread.start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ)
    env.update({"OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_MODELS": str(tmp_path / "models"),
                "OLLAMA_REMOTES": "127.0.0.1", "USERPROFILE": str(tmp_path), "HOME": str(tmp_path)})
    env.pop("OLLAMA_NO_CLOUD", None)
    proc = None
    ready = threading.Event()
    try:
        proc = popen_managed([shutil.which("ollama"), "serve"], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        def drain():
            for line in proc.stderr:
                if "Listening on" in line:
                    ready.set()
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        assert ready.wait(timeout=20), "isolated Ollama did not confirm its listener"
        owner_state = tmp_path / "state"
        owner_state.mkdir()
        (owner_state / "ollama.owner.json").write_text(
            json.dumps(process_owner_record(proc.pid, owner_state, "ollama")), encoding="utf-8")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f"http://127.0.0.1:{port}"
        with opener.open(base + "/api/version", timeout=5) as response:
            assert json.load(response)["version"] == "0.34.0"
        def post(path, data):
            request = urllib.request.Request(base + path, data=json.dumps(data).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
            return opener.open(request, timeout=10)
        with post("/api/create", {"model": "innocent-alias", "from": "remote-model", "remote_host": f"http://127.0.0.1:{remote.server_port}", "stream": False}) as response:
            assert json.load(response)["status"] == "success"
        with opener.open(base + "/api/tags", timeout=5) as response:
            rows = json.load(response)["models"]
        assert any(row.get("name") == "innocent-alias:latest" and row.get("remote_host") for row in rows)
        prompt = {"messages": [{"role": "user", "content": "isolated probe"}], "stream": False}
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            checked_socket = _preflight_connection(connection, "innocent-alias", lambda sock: verify_supervised_peer(sock, owner_state))
            assert connection.sock is checked_socket
            connection.request("POST", "/v1/chat/completions", body=json.dumps({**prompt, "model": "innocent-alias:local"}),
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            assert response.status == 404
            response.read()
        finally:
            connection.close()
        assert remote_requests == []
        try:
            with post("/v1/chat/completions", {**prompt, "model": "innocent-alias"}) as response:
                response.read()
        except urllib.error.HTTPError as error:
            error.close()
        assert remote_requests, "control request did not reach the loopback remote"
    finally:
        try:
            if proc is not None:
                assert terminate_tree(proc.pid, process_handle=proc), "isolated Ollama cleanup unconfirmed"
                proc.wait(timeout=5)
                reader.join(timeout=3)
                proc.stderr.close()
        finally:
            remote.shutdown()
            remote.server_close()
            remote_thread.join(timeout=3)
