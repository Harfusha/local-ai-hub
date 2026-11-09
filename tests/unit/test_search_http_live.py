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


def test_hint_directory_candidates_filter_lexically_without_resolving(tmp_path, monkeypatch):
    from pathlib import Path

    from local_ai_hub.services import LocalAIServices

    root = tmp_path.resolve()
    hinted_directory = root / "src"
    hinted_directory.mkdir()
    inside = hinted_directory / "inside.py"
    inside.write_text("pass\n", encoding="utf-8")
    outside = root / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    relative_inside = Path("src") / "relative.py"
    escaped_relative = Path("src") / ".." / "outside.py"
    external = root.parent / "external.py"

    def unexpected_resolve(_path, *args, **kwargs):
        raise AssertionError("inventory filtering must not resolve every file")

    monkeypatch.setattr(type(root), "resolve", unexpected_resolve)
    candidates = list(LocalAIServices._hint_directory_candidates(
        [inside, relative_inside, outside, escaped_relative, external],
        root,
        hinted_directory,
    ))

    assert candidates == [inside, root / relative_inside]


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
        'auto_start_ollama=false\n[security]\n'
        f'allowed_roots=[{json.dumps(str(root))}]\n'
        '[hardware]\nprofile="cpu"\nauto_tune=false\n[prewarm]\nenabled=false\n'
        '[preprocessing]\nenabled=false\nfs_watcher_enabled=false\n'
        '[features]\npreprocessing=false\n[resilience]\nwatchdog_enabled=false\n'
        '[code_intelligence]\nenabled=false\n[observability]\nenabled=false\n'
        '[debug_traces]\nenabled=true\n', encoding="utf-8")
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
            body = json.dumps({"root": str(root), "query": "C++", "limit": 10, "exact_count": True}).encode()
            request = urllib.request.Request(f"http://127.0.0.1:{port}/api/search", data=body,
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)

        first = search()
        assert first["success"] is True, first.get("error", first)
        assert [item["path"] for item in first["results"]] == ["bridge.py"]
        assert isinstance(first.get("phase_timings_ms"), dict)
        assert first["phase_timings_ms"]["repo_tools_search_ms"] >= 0
        assert first["phase_timings_ms"]["search_preparation_ms"] >= 0
        assert first["phase_timings_ms"]["search_saved_hints_ms"] >= 0
        assert first["phase_timings_ms"]["search_hint_digest_ms"] >= 0
        assert first["phase_timings_ms"]["search_learning_record_ms"] >= 0
        assert first["phase_timings_ms"]["result_materialization_ms"] >= 0
        profile_body = json.dumps({"root": str(root), "query": "bridge", "limit": 10}).encode()
        profile_request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/search",
            data=profile_body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(profile_request, timeout=15) as response:
            profiled = json.load(response)
        assert profiled["success"] is True
        assert profiled["phase_timings_ms"]["search_hint_state_ms"] >= 0
        assert profiled["phase_timings_ms"]["search_hint_inventory_ms"] >= 0
        assert profiled["phase_timings_ms"]["search_hint_path_validation_ms"] >= 0
        assert profiled["phase_timings_ms"]["search_priority_setup_ms"] >= 0
        assert profiled["phase_timings_ms"]["search_result_path_validation_ms"] >= 0
        assert profiled["phase_timings_ms"]["search_result_prioritization_ms"] >= 0
        assert profiled["phase_timings_ms"]["repo_tools_candidate_discovery_ms"] >= 0
        assert profiled["phase_timings_ms"]["repo_tools_git_inventory_ms"] >= 0
        assert profiled["phase_timings_ms"]["repo_tools_project_file_iteration_ms"] >= 0
        assert profiled["phase_timings_ms"]["repo_tools_candidate_priority_sort_ms"] >= 0
        assert profiled["phase_timings_ms"]["repo_tools_candidate_path_validation_ms"] >= 0
        assert profiled["phase_timings_ms"]["repo_tools_accelerator_search_ms"] >= 0
        assert profiled["phase_timings_ms"]["repo_tools_candidate_scan_ms"] >= 0
        path.write_text("# unrelated bridge\n", encoding="utf-8")
        second = search()
        assert second["success"] is True
        assert second["total_matches"] == 0
        assert second["results"] == []
    finally:
        _terminate_selftest_process(process, identity)
