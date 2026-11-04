"""Benchmark real loopback HTTP search against an isolated labeled fixture.

Starts and terminates its own CPU-only supervisor and temporary state. It does
not connect to or change the operator's running Hub.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from local_ai_hub.process_utils import popen_managed, process_identity
if __package__:
    from tools.benchmark_search_quality import evaluate, make_fixture, make_holdout_fixture
    from tools.selftest import ROOT, SRC, _free_port, _get_json, _terminate_selftest_process
else:
    from benchmark_search_quality import evaluate, make_fixture, make_holdout_fixture
    from selftest import ROOT, SRC, _free_port, _get_json, _terminate_selftest_process


def run(repeats: int = 3, noise_files: int = 100, suite: str = "holdout") -> dict:
    if repeats < 1 or noise_files < 0 or suite not in {"development", "holdout"}:
        raise ValueError("invalid benchmark arguments")
    with tempfile.TemporaryDirectory(prefix="hub-http-search-", ignore_cleanup_errors=True) as directory:
        temp = Path(directory)
        root = temp / "repo"
        root.mkdir()
        cases = (make_fixture if suite == "development" else make_holdout_fixture)(root, noise_files)
        state, port = temp / "state", _free_port()
        config = temp / "config.toml"
        config.write_text(
            f'[server]\nbind="127.0.0.1"\nport={port}\nstate_dir={json.dumps(str(state))}\n'
            'ollama_url="http://127.0.0.1:9"\nauto_start_ollama=false\n[security]\napi_token=""\n'
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
            rows = []
            for case in cases:
                timings, hits = [], []
                for _ in range(repeats):
                    payload = json.dumps({"root": str(root), "query": case["query"], "limit": 10}).encode()
                    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/search", data=payload,
                                                     headers={"Content-Type": "application/json"})
                    started = time.perf_counter()
                    with urllib.request.urlopen(request, timeout=20) as response:
                        result = json.load(response)
                    timings.append((time.perf_counter() - started) * 1000)
                    if not result.get("success"):
                        raise RuntimeError(f"search failed for {case['query']!r}: {result.get('error')}")
                    hits.append(result.get("cache_hit"))
                paths = [item["path"] for item in result["results"]]
                rows.append({"query": case["query"], "expected": case["relevant"], "paths": paths,
                             **evaluate(paths, case["relevant"]), "samples_ms": timings, "cache_hits": hits})
            return {"scope": "isolated local supervisor and HTTP /api/search; CPU profile, preprocessing disabled",
                    "suite": suite, "noise_files": noise_files, "repeats": repeats, "cases": rows}
        finally:
            _terminate_selftest_process(process, identity)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--noise-files", type=int, default=100)
    parser.add_argument("--suite", choices=("development", "holdout"), default="holdout")
    args = parser.parse_args()
    print(json.dumps(run(args.repeats, args.noise_files, args.suite), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
