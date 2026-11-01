import subprocess
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from local_ai_hub.opencode_models import ModelPreparationError, ensure_model, local_inventory, local_pull


def test_present_model_does_not_pull():
    result = ensure_model("qwen3.5:9b", inventory=lambda: {"qwen3.5:9b"}, pull=lambda _: pytest.fail("pulled"))
    assert result == {"model": "qwen3.5:9b", "installed": True, "downloaded": False, "runtime_verified": False}


def test_untagged_model_accepts_default_latest_tag():
    result = ensure_model("qwen3.5", inventory=lambda: {"qwen3.5:latest"}, pull=lambda _: pytest.fail("pulled"))
    assert result["downloaded"] is False


def test_missing_model_pulled_once_and_inventory_rechecked():
    reads = iter([set(), {"qwen3.5:9b"}])
    calls = []
    result = ensure_model("qwen3.5:9b", inventory=lambda: next(reads), pull=lambda model: calls.append(model))
    assert calls == ["qwen3.5:9b"]
    assert result["downloaded"] is True
    assert result["runtime_verified"] is False


def test_missing_model_when_pulls_disabled_fails_without_calling_pull():
    with pytest.raises(ModelPreparationError, match="not installed"):
        ensure_model("qwen3.5:9b", inventory=lambda: set(), pull=lambda _: pytest.fail("pulled"), allow_pull=False)


def test_timeout_is_unknown_and_never_retried():
    calls = []
    def pull(model):
        calls.append(model)
        raise subprocess.TimeoutExpired("ollama", 1)
    with pytest.raises(ModelPreparationError, match="outcome unknown"):
        ensure_model("qwen3.5:9b", inventory=lambda: set(), pull=pull)
    assert calls == ["qwen3.5:9b"]


def test_successful_pull_without_inventory_confirmation_is_failure():
    with pytest.raises(ModelPreparationError, match="not confirmed"):
        ensure_model("qwen3.5:9b", inventory=lambda: set(), pull=lambda _: None)


@pytest.mark.parametrize("model", ["-bad", "bad model", "", "x\nother"])
def test_invalid_model_never_queries_backend(model):
    with pytest.raises(ValueError):
        ensure_model(model, inventory=lambda: pytest.fail("queried"), pull=lambda _: pytest.fail("pulled"))


def test_loopback_inventory_reads_real_http_and_rejects_non_loopback():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/api/tags"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"models": [{"name": "qwen3.5:9b"}]}).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert local_inventory(f"http://127.0.0.1:{server.server_port}") == {"qwen3.5:9b"}
        with pytest.raises(ValueError):
            local_inventory("http://192.0.2.1:11434")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_loopback_inventory_refuses_redirects():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://192.0.2.1:80/api/tags")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(ModelPreparationError):
            local_inventory(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_pull_uses_explicit_local_origin_and_argv(monkeypatch):
    from local_ai_hub import opencode_models
    seen = {}
    monkeypatch.setattr(opencode_models, "run_hidden", lambda argv, **kwargs: seen.update(argv=argv, **kwargs))
    local_pull("ollama", "http://127.0.0.1:11434", "qwen3.5:9b")
    assert seen["argv"] == ["ollama", "pull", "qwen3.5:9b"]
    assert seen["env"]["OLLAMA_HOST"] == "http://127.0.0.1:11434"
    assert seen["timeout"] == 1800


def test_unconfirmed_process_cleanup_is_unknown_and_not_retried():
    from local_ai_hub.process_utils import ProcessCleanupUnverifiedError
    calls = []
    def pull(model):
        calls.append(model)
        raise ProcessCleanupUnverifiedError(["ollama"], process=None, tree_termination_confirmed=False)
    with pytest.raises(ModelPreparationError, match="outcome unknown"):
        ensure_model("qwen3.5:9b", inventory=lambda: set(), pull=pull)
    assert calls == ["qwen3.5:9b"]


def test_real_managed_process_failure_is_reported_without_output(tmp_path):
    import sys
    with pytest.raises(subprocess.CalledProcessError):
        local_pull(sys.executable, "http://127.0.0.1:11434", "qwen3.5:9b", timeout=5)


def test_setup_prepares_only_requested_model_without_installing_existing(monkeypatch, capsys):
    import sys
    from local_ai_hub import opencode_models
    from tools import setup
    monkeypatch.setattr(opencode_models, "local_inventory", lambda origin: {"qwen3.5:9b"})
    monkeypatch.setattr(opencode_models, "local_pull", lambda *a: pytest.fail("pulled existing model"))
    monkeypatch.setattr(setup, "copy_install_tree", lambda *a, **k: pytest.fail("ran full setup"))
    monkeypatch.setattr(sys, "argv", ["setup.py", "--prepare-opencode-model", "qwen3.5:9b"])
    assert setup.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["installed"] is True
    assert result["runtime_verified"] is False
    assert result["downloaded"] is False


def test_setup_model_preparation_rejects_unrelated_options(monkeypatch):
    import sys
    from tools import setup
    monkeypatch.setattr(sys, "argv", ["setup.py", "--prepare-opencode-model", "qwen3.5:9b", "--generate-only"])
    with pytest.raises(SystemExit):
        setup.main()


def test_setup_script_direct_process_with_loopback_inventory(tmp_path):
    import sys
    from pathlib import Path
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"models":[{"name":"qwen3.5:9b"}]}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script = Path(__file__).resolve().parents[1] / "tools" / "setup.py"
        result = subprocess.run([sys.executable, str(script), "--prepare-opencode-model", "qwen3.5:9b",
                                 "--opencode-ollama-url", f"http://127.0.0.1:{server.server_port}",
                                 "--skip-model-pull"], cwd=tmp_path, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["runtime_verified"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
