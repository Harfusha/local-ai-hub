"""Measure repeated code-index inventory validation with and without revision caching.

The benchmark is synthetic, writes only to a temporary directory, and does not
start model inference or modify the repository's configured state.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.preprocess import ProjectPreprocessor, _ensure_file_refs_revision_tracking
from local_ai_hub.repo_tools import RepositoryTools


class _CodeIndex:
    def __init__(self) -> None:
        self.indexed: set[str] = set()

    def prune(self, _root: str, _paths) -> dict:
        return {"success": True}

    def record_usage(self, *_args) -> None:
        return None

    def files_needing_reindex(self, _root: str, refs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return [(path, digest) for path, digest in refs if path not in self.indexed]

    def update_files_batch(self, _root: str, pending: list[tuple[str, str]]) -> dict:
        self.indexed.update(path for path, _digest in pending)
        return {"files_processed": len(pending), "cached": 0}


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)] if ordered else 0.0


def _make_preprocessor(root: str, db: Path, evidence: EvidenceStore, *, cached: bool):
    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock = threading.RLock()
    pre._stats_lock = threading.Lock()
    pre._connect = connect
    pre._stats = {"code_index_files": 0}
    pre._missing_refs_checked_generations = {(root, 1)}
    pre._project_settings = lambda _root: None
    pre._set_project = lambda *_args, **_kwargs: None
    pre._record_progress = lambda *_args: None
    pre.cfg = {"code_index_files_per_step": 1}
    pre.repo_tools = RepositoryTools({})
    pre.code_index = _CodeIndex()
    pre.services = SimpleNamespace(evidence_store=evidence)
    checks = [0]

    def path_allowed(_root, _path, *_args, **_kwargs):
        checks[0] += 1
        return True

    pre._project_path_allowed = path_allowed
    if cached:
        pre._code_index_allowed_cache_lock = threading.Lock()
        pre._code_index_allowed_cache = {}
    return pre, checks


def _run_case(root: Path, db: Path, evidence: EvidenceStore, demand_files: int, *, cached: bool) -> dict:
    root_s = str(root)
    pre, path_checks = _make_preprocessor(root_s, db, evidence, cached=cached)
    samples_ms = []
    started = time.perf_counter()
    for _ in range(demand_files + 1):
        step_started = time.perf_counter()
        pre._step_code_index({"root": root_s, "generation": 1})
        samples_ms.append((time.perf_counter() - step_started) * 1000)
    if len(pre.code_index.indexed) != demand_files:
        raise RuntimeError("code-index demand fixture did not finish")
    return {
        "mode": "revision_cache" if cached else "full_rescan",
        "files_in_inventory": None,
        "demand_files": demand_files,
        "completed_files": len(pre.code_index.indexed),
        "path_policy_checks": path_checks[0],
        "total_ms": round((time.perf_counter() - started) * 1000, 3),
        "step_median_ms": round(statistics.median(samples_ms), 3),
        "step_p95_ms": round(_percentile(samples_ms, 0.95), 3),
    }


def run(*, files: int = 5000, demand_files: int = 32, repeats: int = 3) -> dict:
    if type(files) is not int or files < 1 or files > 50_000:
        raise ValueError("files must be an integer in 1..50000")
    if type(demand_files) is not int or demand_files < 1 or demand_files > min(256, files):
        raise ValueError("demand_files must be an integer in 1..min(256, files)")
    if type(repeats) is not int or repeats < 1 or repeats > 20:
        raise ValueError("repeats must be an integer in 1..20")

    with tempfile.TemporaryDirectory(prefix="local-ai-code-index-cache-") as temp_dir:
        base = Path(temp_dir)
        root = base / "repo"
        root.mkdir()
        db = base / "preprocess.sqlite3"
        with closing(sqlite3.connect(db)) as con:
            con.execute(
                "CREATE TABLE file_refs(root TEXT,path TEXT,content_hash TEXT,size INTEGER,needs_hash INTEGER)"
            )
            _ensure_file_refs_revision_tracking(con)
            rows = []
            for index in range(files):
                path = f"file_{index:05}.py"
                (root / path).write_text("VALUE = 1\n", encoding="utf-8")
                rows.append((str(root), path, f"hash-{index}", 10, 0))
            con.executemany("INSERT INTO file_refs VALUES(?,?,?,?,?)", rows)
            con.commit()

        evidence = EvidenceStore(base / "evidence")
        for index in range(demand_files):
            path = f"file_{index:05}.py"
            evidence.put(str(root), {"path": path, "text": "VALUE = 1", "content_hash": f"hash-{index}"})

        results = {"full_rescan": [], "revision_cache": []}
        for _ in range(repeats):
            for cached, key in ((False, "full_rescan"), (True, "revision_cache")):
                item = _run_case(root, db, evidence, demand_files, cached=cached)
                item["files_in_inventory"] = files
                results[key].append(item)

        aggregate = {}
        for key, samples in results.items():
            aggregate[key] = {
                "path_policy_checks_median": int(statistics.median(item["path_policy_checks"] for item in samples)),
                "total_ms_median": round(statistics.median(item["total_ms"] for item in samples), 3),
                "total_ms_p95": round(_percentile([item["total_ms"] for item in samples], 0.95), 3),
                "step_median_ms": round(statistics.median(item["step_median_ms"] for item in samples), 3),
                "step_p95_ms": round(statistics.median(item["step_p95_ms"] for item in samples), 3),
            }
        before = aggregate["full_rescan"]["path_policy_checks_median"]
        after = aggregate["revision_cache"]["path_policy_checks_median"]
        aggregate["path_policy_check_reduction_percent"] = round((before - after) * 100 / before, 2) if before else 0.0
        before_ms = aggregate["full_rescan"]["total_ms_median"]
        after_ms = aggregate["revision_cache"]["total_ms_median"]
        aggregate["total_time_reduction_percent"] = round((before_ms - after_ms) * 100 / before_ms, 2) if before_ms else 0.0
        return {
            "benchmark": "synthetic_code_index_allowed_path_cache",
            "files_in_inventory": files,
            "demand_files": demand_files,
            "repeats": repeats,
            "results": aggregate,
            "samples": results,
            "limitations": ["synthetic filesystem and in-memory code-index writer", "no model inference", "warm local OS cache"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=5000)
    parser.add_argument("--demand-files", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run(files=args.files, demand_files=args.demand_files, repeats=args.repeats), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
