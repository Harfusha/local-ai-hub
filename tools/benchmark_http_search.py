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


def build_search_payload(root: str, query: str, search_mode: str) -> dict[str, object]:
    if search_mode not in {"default", "lexical", "rag", "hybrid"}:
        raise ValueError("invalid search_mode")
    payload: dict[str, object] = {"root": root, "query": query, "limit": 10}
    if search_mode != "default":
        payload["search_mode"] = search_mode
    return payload


def run(
    repeats: int = 3,
    noise_files: int = 100,
    suite: str = "holdout",
    search_mode: str = "default",
) -> dict:
    if (repeats < 1 or noise_files < 0 or suite not in {"development", "holdout"}
            or search_mode not in {"default", "lexical", "rag", "hybrid"}):
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
                    payload = json.dumps(build_search_payload(str(root), case["query"], search_mode)).encode()
                    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/search", data=payload,
                                                     headers={"Content-Type": "application/json"})
                    started = time.perf_counter()
                    try:
                        with urllib.request.urlopen(request, timeout=20) as response:
                            result = json.load(response)
                    except urllib.error.HTTPError as response:
                        result = json.load(response)
                    timings.append((time.perf_counter() - started) * 1000)
                    hits.append(result.get("cache_hit"))
                succeeded = result.get("success") is True
                paths = [item["path"] for item in result.get("results", [])] if succeeded else []
                reranker = result.get("reranker")
                rows.append({"query": case["query"], "expected": case["relevant"], "paths": paths,
                             **evaluate(paths, case["relevant"]), "samples_ms": timings, "cache_hits": hits,
                             "success": succeeded, "error": result.get("error"),
                             "actual_search_mode": result.get("search_mode"),
                             "result_source": result.get("result_source"),
                             "degraded": result.get("degraded"),
                             "degradation_reason": result.get("degradation_reason"),
                             "query_expansion_applied": result.get("query_expansion_applied"),
                             "reranker_requested": reranker.get("requested") if isinstance(reranker, dict) else None,
                             "reranker_used": reranker.get("used") if isinstance(reranker, dict) else None})
            return {"scope": "isolated local supervisor and HTTP /api/search; CPU profile, preprocessing disabled",
                    "suite": suite, "search_mode": search_mode, "noise_files": noise_files,
                    "repeats": repeats, "cases": rows}
        finally:
            _terminate_selftest_process(process, identity)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--noise-files", type=int, default=100)
    parser.add_argument("--suite", choices=("development", "holdout"), default="holdout")
    parser.add_argument("--search-mode", choices=("default", "lexical", "rag", "hybrid"), default="default")
    args = parser.parse_args()
    print(json.dumps(run(args.repeats, args.noise_files, args.suite, args.search_mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
