"""Isolated supervisor and HTTP search roundtrip, with no production state."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from local_ai_hub.process_utils import popen_managed, process_identity
from tools.selftest import ROOT, SRC, _free_port, _get_json, _terminate_selftest_process


def test_live_http_search_literal_and_freshness(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    path = root / "bridge.py"
    path.write_text("# C++ bridge\n", encoding="utf-8")
    state = tmp_path / "state"
    port = _free_port()
    config = tmp_path / "config.toml"
    config.write_text(
        f'[server]\nbind="127.0.0.1"\nport={port}\nstate_dir={json.dumps(str(state))}\n'
        'auto_start_ollama=false\n[security]\napi_token=""\n'
        f'allowed_roots=[{json.dumps(str(root))}]\n'
        '[hardware]\nprofile="cpu"\nauto_tune=false\n[prewarm]\nenabled=false\n'
        '[preprocessing]\nenabled=false\nfs_watcher_enabled=false\n'
        '[features]\npreprocessing=false\n[resilience]\nwatchdog_enabled=false\n'
        '[code_intelligence]\nenabled=false\n[observability]\nenabled=false\n', encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["LOCAL_AI_CONFIG"] = str(config)
    process = popen_managed([sys.executable, "-m", "local_ai_hub.supervisor"], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    identity = process_identity(process.pid)
    try:
        deadline = time.monotonic() + 30
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"isolated supervisor exited: {process.returncode}")
            try:
                if _get_json(f"http://127.0.0.1:{port}/health")["success"]:
                    break
            except (OSError, urllib.error.URLError):
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("isolated supervisor health timeout")
            time.sleep(0.1)

        def search():
            body = json.dumps({"root": str(root), "query": "C++", "limit": 10}).encode()
            request = urllib.request.Request(f"http://127.0.0.1:{port}/api/search", data=body,
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)

        first = search()
        assert first["success"] is True
        assert [item["path"] for item in first["results"]] == ["bridge.py"]
        path.write_text("# unrelated bridge\n", encoding="utf-8")
        second = search()
        assert second["success"] is True
        assert second["total_matches"] == 0
        assert second["results"] == []
    finally:
        _terminate_selftest_process(process, identity)
