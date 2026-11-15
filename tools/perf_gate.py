"""Performance Regression Quality Gate for Local AI Hub (HUB-109).

Executes controlled benchmarks for core CPU/database algorithms:
- Exact search latency
- Search fusion candidate deduplication (HUB-083/084)
- Evidence interval merging (HUB-085/088)
- Source outline AST extraction (HUB-089/090)
- Idle RAG inventory digest bypass (HUB-091)
- Content hash SQLite index verification (HUB-082)

Measures p50, p95, and asserts results against regression ceilings defined in
docs/PERFORMANCE_REGRESSION_BUDGET.md.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

from local_ai_hub.evidence_merge import merge_overlapping_line_ranges
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.search_fusion import fuse_search_candidates
from local_ai_hub.source_outline import ast_outline


BUDGETS_MS: dict[str, float] = {
    "search_fusion_p50": 50.0,
    "search_fusion_p95": 80.0,
    "evidence_merge_p50": 10.0,
    "evidence_merge_p95": 20.0,
    "source_outline_p50": 30.0,
    "source_outline_p95": 50.0,
    "idle_rag_step_p50": 10.0,
    "idle_rag_step_p95": 20.0,
    "hash_index_lookup_p50": 10.0,
    "hash_index_lookup_p95": 20.0,
}


def _run_search_fusion(iterations: int = 5) -> list[float]:
    times: list[float] = []
    l1 = [{"path": f"src/file_{i}.py", "line": i, "relevance": 0.9} for i in range(500)]
    l2 = [{"path": f"src/file_{i}.py", "line": i, "relevance": 0.8} for i in range(250, 750)]
    for _ in range(iterations):
        t0 = time.perf_counter()
        res = fuse_search_candidates(l1, l2)
        t1 = time.perf_counter()
        if not res:
            raise RuntimeError("search fusion returned empty results")
        times.append((t1 - t0) * 1000.0)
    return times


def _run_evidence_merge(iterations: int = 5) -> list[float]:
    times: list[float] = []
    intervals = [(i, i + 5) for i in range(1, 1000, 3)]
    for _ in range(iterations):
        t0 = time.perf_counter()
        res = merge_overlapping_line_ranges(intervals)
        t1 = time.perf_counter()
        if not res:
            raise RuntimeError("evidence merge returned empty results")
        times.append((t1 - t0) * 1000.0)
    return times


def _run_source_outline(iterations: int = 5) -> list[float]:
    times: list[float] = []
    target = Path("src/local_ai_hub/agent_identity.py")
    if not target.exists():
        raise FileNotFoundError(f"target file not found: {target}")
    for _ in range(iterations):
        t0 = time.perf_counter()
        res = ast_outline(".", str(target))
        t1 = time.perf_counter()
        if res.get("success") is not True:
            raise RuntimeError(f"ast_outline failed: {res.get('error')}")
        times.append((t1 - t0) * 1000.0)
    return times


def _run_idle_rag_step(iterations: int = 5) -> list[float]:
    import tempfile
    td = tempfile.TemporaryDirectory()
    db_path = Path(td.name) / "test.db"
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    with con:
        con.execute(
            "CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, "
            "needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL, size INTEGER, updated_at REAL)"
        )
        con.execute("CREATE TABLE file_refs_revision(root TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0)")
        con.execute("CREATE TABLE projects(root TEXT, phase TEXT, status TEXT, updated_at REAL)")
        con.executemany(
            "INSERT INTO file_refs VALUES('repo', ?, 'hash', 0, 'hash', 0, 10, 0)",
            [(f"file_{i}.py",) for i in range(1000)],
        )
        con.execute("INSERT INTO file_refs_revision VALUES('repo', 1)")
        con.execute("INSERT INTO projects VALUES('repo', 'rag', 'running', 0)")
    con.close()

    def get_con():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    class MockRag:
        def indexed_paths(self, workspace: str, paths: list[str]) -> set[str]:
            return set(paths)

        def prune_missing(self, root: str, workspace: str, all_paths: list[str]) -> int:
            return 0

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock = threading.RLock()
    pre._stats_lock = threading.RLock()
    pre._stats = {}
    pre._rag_inventory_digests = {}
    pre._connect = get_con
    pre._yield = lambda: False
    pre.cfg = {"rag_idle_audit_cadence_seconds": 300.0}
    pre.deterministic = None
    pre.rag = MockRag()
    pre._set_project = lambda r, **kwargs: None

    # Warmup / initial baseline populate
    pre._step_rag({"root": "repo", "workspace": "ws"})

    times: list[float] = []
    try:
        for _ in range(iterations):
            t0 = time.perf_counter()
            ok = pre._step_rag({"root": "repo", "workspace": "ws"})
            t1 = time.perf_counter()
            if not ok:
                raise RuntimeError("idle _step_rag failed")
            times.append((t1 - t0) * 1000.0)
    finally:
        td.cleanup()
    return times


def _run_hash_index_lookup(iterations: int = 5) -> list[float]:
    times: list[float] = []
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    with con:
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)")
        con.execute("CREATE INDEX idx_source_index_hash ON source_index(content_hash)")
        con.executemany(
            "INSERT INTO source_index VALUES('repo', ?, ?, 'sample text')",
            [(f"file_{i}.py", f"hash_{i % 50}") for i in range(5000)],
        )

    for _ in range(iterations):
        t0 = time.perf_counter()
        rows = con.execute(
            "SELECT path FROM source_index WHERE content_hash IN ('hash_1', 'hash_2', 'hash_3')"
        ).fetchall()
        t1 = time.perf_counter()
        if not rows:
            raise RuntimeError("hash index query returned no rows")
        times.append((t1 - t0) * 1000.0)
    return times


def _percentiles(samples: list[float]) -> tuple[float, float]:
    sorted_s = sorted(samples)
    p50 = sorted_s[len(sorted_s) // 2]
    p95_idx = min(len(sorted_s) - 1, int(len(sorted_s) * 0.95))
    p95 = sorted_s[p95_idx]
    return p50, p95


def run_all(iterations: int = 7) -> dict[str, Any]:
    suite = {
        "search_fusion": _run_search_fusion(iterations),
        "evidence_merge": _run_evidence_merge(iterations),
        "source_outline": _run_source_outline(iterations),
        "idle_rag_step": _run_idle_rag_step(iterations),
        "hash_index_lookup": _run_hash_index_lookup(iterations),
    }

    results: dict[str, Any] = {}
    violations: list[str] = []

    for name, samples in suite.items():
        p50, p95 = _percentiles(samples)
        b_p50 = BUDGETS_MS[f"{name}_p50"]
        b_p95 = BUDGETS_MS[f"{name}_p95"]

        results[f"{name}_p50_ms"] = round(p50, 3)
        results[f"{name}_p95_ms"] = round(p95, 3)
        results[f"{name}_budget_p50_ms"] = b_p50
        results[f"{name}_budget_p95_ms"] = b_p95
        results[f"{name}_passed"] = p50 <= b_p50 and p95 <= b_p95

        if p50 > b_p50:
            violations.append(f"{name} p50={p50:.2f}ms exceeds budget {b_p50:.2f}ms")
        if p95 > b_p95:
            violations.append(f"{name} p95={p95:.2f}ms exceeds budget {b_p95:.2f}ms")

    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            check=True, timeout=3,
        ).stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        revision = None
    return {
        "scope": "synthetic_microbench_only",
        "repository_workload": "NOT_RUN",
        "model_pipeline": "NOT_RUN",
        "environment": {
            "git_head_sha": revision,
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
        },
        "success": len(violations) == 0,
        "iterations": iterations,
        "metrics": results,
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Local AI Hub Performance Quality Gate")
    parser.add_argument("--iterations", type=int, default=7, help="Samples per benchmark")
    parser.add_argument("--output", type=str, default="", help="JSON report output path")
    args = parser.parse_args()

    report = run_all(iterations=args.iterations)

    print("=" * 60)
    print("Local AI Hub Performance Quality Gate (HUB-109)")
    print("=" * 60)
    for k, v in report["metrics"].items():
        print(f"  {k:30s}: {v}")

    if report["violations"]:
        print("\nREGRESSION FAILURES:")
        for v in report["violations"]:
            print(f"  [FAIL] {v}")
    else:
        print("\nSYNTHETIC MICROBENCH BUDGETS SATISFIED (full workload/model pipeline NOT RUN)")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport written to {args.output}")

    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
