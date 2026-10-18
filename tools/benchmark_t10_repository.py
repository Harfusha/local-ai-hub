"""Measure T10 repository scan, parser, SQLite, graph, and bounded search paths.

This runner writes only to its temporary workspace and the optional output path.
It does not start the Hub server or invoke external code-intelligence backends.
The default search probe may use local ripgrep or Git; a separately capped Python
fallback measurement prevents accelerator timeouts from being scored as search quality.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import ctypes
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
import sysconfig

SOURCE_ROOT = Path(os.environ.get("T10_BENCH_SOURCE_ROOT") or Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, str(SOURCE_ROOT))

from local_ai_hub import code_index as code_index_module
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.retrieval import fuse_ranked_paths
from local_ai_hub import treesitter_parser
from local_ai_hub.treesitter_parser import is_treesitter_available


def _code_index_impact_cap(module: Any) -> int:
    value = getattr(module, "MAX_IMPACT_DEPENDENTS", None)
    return max(1, int(value)) if value is not None else 100


CodeIndex = code_index_module.CodeIndex
MAX_IMPACT_DEPENDENTS = _code_index_impact_cap(code_index_module)


def _parser_runtime_metadata(parser_backend_requested: str = "auto") -> dict[str, Any]:
    try:
        language_pack_version = package_version("tree-sitter-language-pack")
    except PackageNotFoundError:
        language_pack_version = None
    parser_available = is_treesitter_available("python")
    return {
        "parser_backend_requested": parser_backend_requested,
        "parser_backend_used": "tree_sitter" if parser_available else "fallback",
        "tree_sitter_python_available": parser_available,
        "tree_sitter_language_pack_version": language_pack_version,
    }


def _configure_parser_backend(parser_backend: str) -> dict[str, Any]:
    if parser_backend not in {"auto", "fallback"}:
        raise ValueError(f"unsupported parser backend: {parser_backend}")
    if parser_backend == "fallback":
        with treesitter_parser._PARSER_LOCK:
            treesitter_parser._PARSERS.clear()
            treesitter_parser._LANGUAGES.clear()
            treesitter_parser._INIT_ATTEMPTED = True
    return _parser_runtime_metadata(parser_backend)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return _percentile_sorted(ordered, percentile)


def _percentile_sorted(ordered: list[float], percentile: float) -> float:
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction, 4)


def _quantile_ci95_sorted(ordered: list[float], percentile: float) -> list[float] | None:
    sample_count = len(ordered)
    if sample_count < 2:
        return None
    z_score = statistics.NormalDist().inv_cdf(0.975)
    radius = z_score * math.sqrt(sample_count * percentile * (1 - percentile))
    lower_rank = max(1, math.floor(sample_count * percentile - radius))
    upper_rank = min(sample_count, math.ceil(sample_count * percentile + radius))
    return [round(ordered[lower_rank - 1], 4), round(ordered[upper_rank - 1], 4)]


def _summary(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "samples": len(values),
        "p50_ms": _percentile_sorted(ordered, 0.50) if ordered else None,
        "p95_ms": _percentile_sorted(ordered, 0.95) if ordered else None,
        "p99_ms": _percentile_sorted(ordered, 0.99) if ordered else None,
        "p95_ci95_ms": _quantile_ci95_sorted(ordered, 0.95),
        "p99_ci95_ms": _quantile_ci95_sorted(ordered, 0.99),
        "uncertainty_method": "binomial_order_statistic_normal_approximation",
        "mean_ms": round(statistics.fmean(values), 4) if values else None,
    }


def _summary_with_samples(values: list[float]) -> dict[str, Any]:
    summary = _summary(values)
    summary["raw_ms"] = [round(value, 4) for value in values]
    return summary


def _ranking_metrics(observed: list[Any], relevant: set[Any], k: int = 10) -> dict[str, Any]:
    if k < 1:
        raise ValueError("k must be positive")
    ranked = observed[:k]
    relevance = [item in relevant for item in ranked]
    relevant_in_top_k = sum(relevance)
    dcg = sum(1 / math.log2(rank + 2) for rank, is_relevant in enumerate(relevance) if is_relevant)
    ideal_relevant = min(k, len(relevant))
    idcg = sum(1 / math.log2(rank + 2) for rank in range(ideal_relevant))
    return {
        "k": k,
        "observed_count": len(observed),
        "relevant_count": len(relevant),
        "relevant_in_top_k": relevant_in_top_k,
        "precision_at_k": round(relevant_in_top_k / k, 4),
        "recall_at_k": round(relevant_in_top_k / len(relevant), 4) if relevant else None,
        "ndcg_at_k": round(dcg / idcg, 4) if idcg else None,
    }


def _search_line_evidence(results: list[dict[str, Any]], needle: str) -> list[tuple[str, int]]:
    evidence: list[tuple[str, int]] = []
    for result in results:
        path = str(result.get("path") or "")
        for snippet_line in str(result.get("text") or "").splitlines():
            line_number, separator, content = snippet_line.partition(":")
            if not separator or needle not in content:
                continue
            try:
                evidence.append((path, int(line_number.strip())))
            except ValueError:
                continue
    return evidence


def _measure_concurrent_workload(callback, workers: int, sample_count: int) -> dict[str, Any]:
    if workers < 1 or sample_count < workers:
        raise ValueError("sample_count must be at least the positive worker count")

    start_barrier = threading.Barrier(workers)

    def run_one(sample_index: int) -> tuple[float, bool, bool, bool, bool, bool, str | None]:
        if sample_index < workers:
            try:
                start_barrier.wait(timeout=30)
            except threading.BrokenBarrierError:
                return 0.0, False, False, False, False, False, "barrier_timeout"
        started = time.perf_counter()
        try:
            result = callback()
        except Exception as exc:
            return (time.perf_counter() - started) * 1000, False, False, False, False, False, type(exc).__name__
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not isinstance(result, dict):
            return elapsed_ms, False, False, False, False, False, "invalid_response"
        coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
        successful = result.get("success") is True
        error_type = None if successful else "unsuccessful_response"
        return (
            elapsed_ms,
            successful,
            isinstance(result.get("coverage"), dict),
            coverage.get("complete") is True,
            result.get("truncated") is True,
            coverage.get("dependent_candidate_count_exact") is True,
            error_type,
        )

    latencies: list[float] = []
    outcomes = {
        "successful": 0,
        "failed": 0,
        "coverage_reported": 0,
        "coverage_complete": 0,
        "truncated": 0,
        "candidate_count_exact": 0,
    }
    error_types: dict[str, int] = {}
    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="t10-bench") as executor:
        futures = [executor.submit(run_one, index) for index in range(sample_count)]
        for future in as_completed(futures):
            elapsed_ms, successful, has_coverage, complete, truncated, candidate_count_exact, error_type = future.result()
            latencies.append(elapsed_ms)
            outcomes["successful" if successful else "failed"] += 1
            outcomes["coverage_reported"] += int(has_coverage)
            outcomes["coverage_complete"] += int(complete)
            outcomes["truncated"] += int(truncated)
            outcomes["candidate_count_exact"] += int(candidate_count_exact)
            if error_type:
                error_types[error_type] = error_types.get(error_type, 0) + 1
    wall_seconds = max(time.perf_counter() - wall_started, 1e-9)
    return {
        "workers": workers,
        "samples": sample_count,
        "latency": _summary_with_samples(latencies),
        "wall_ms": round(wall_seconds * 1000, 4),
        "throughput_per_second": round(sample_count / wall_seconds, 2),
        "outcomes": outcomes,
        "error_types": dict(sorted(error_types.items())),
    }


def _package_source_tree_sha256(source_root: Path) -> str:
    root = Path(source_root).resolve()
    package = root / "local_ai_hub"
    if not package.is_dir():
        raise FileNotFoundError(f"package source directory not found: {package}")
    digest = hashlib.sha256(b"T10-PACKAGE-SOURCE-TREE-V1\0")
    for path in sorted(
        item for item in package.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    ):
        relative = (Path("src") / path.relative_to(root)).as_posix()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _source_identity() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    source_root = Path(SOURCE_ROOT).resolve()
    benchmark_inputs = [
        "tools/benchmark_t10_repository.py",
        "src/local_ai_hub/code_index.py",
        "src/local_ai_hub/repo_tools.py",
        "src/local_ai_hub/retrieval.py",
        "src/local_ai_hub/treesitter_parser.py",
    ]
    tracked = [
        "README.md",
        "src/local_ai_hub/code_index.py",
        "src/local_ai_hub/deterministic.py",
        "src/local_ai_hub/repo_tools.py",
        "src/local_ai_hub/retrieval.py",
        "src/local_ai_hub/services.py",
        "src/local_ai_hub/treesitter_parser.py",
        "tests/test_adaptive_retrieval.py",
        "tests/test_affected_tests.py",
        "tests/test_codegraph_package_policy.py",
        "tests/test_t10_acceptance.py",
        "tests/test_t10_retrieval_edges.py",
    ]
    head = os.environ.get("T10_BENCH_SOURCE_REVISION")
    patch_hash = os.environ.get("T10_BENCH_SOURCE_FINGERPRINT")
    patch_bytes = 0
    source_root_matches_checkout = source_root == (root / "src").resolve()
    if source_root_matches_checkout and (not head or not patch_hash):
        try:
            if not head:
                head = subprocess.run(
                    ["git", "-C", str(root), "rev-parse", "HEAD"],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                ).stdout.decode("ascii", "replace").strip()
            if not patch_hash:
                patch = subprocess.run(
                    ["git", "-C", str(root), "diff", "HEAD", "--binary", "--full-index", "--no-ext-diff", "--", *tracked],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                ).stdout
                new_file = (root / "tools" / "benchmark_t10_repository.py").read_bytes()
                benchmark_test_path = root / "tests" / "test_t10_benchmark.py"
                benchmark_test = benchmark_test_path.read_bytes() if benchmark_test_path.is_file() else b""
                consumer_test_path = root / "tests" / "test_t10_project_config_consumers.py"
                consumer_test = consumer_test_path.read_bytes() if consumer_test_path.is_file() else b""
                framed = (
                    b"T10-CANDIDATE-PATCH-V1\0" + patch
                    + b"\0UNTRACKED:tools/benchmark_t10_repository.py\0" + new_file
                    + b"\0UNTRACKED:tests/test_t10_benchmark.py\0" + benchmark_test
                    + b"\0UNTRACKED:tests/test_t10_project_config_consumers.py\0" + consumer_test
                )
                patch_hash = hashlib.sha256(framed).hexdigest()
                patch_bytes = len(patch) + len(new_file) + len(benchmark_test) + len(consumer_test)
        except (OSError, subprocess.CalledProcessError):
            head = head or None
            patch_hash = patch_hash or None
    framed_inputs = []
    for relative in benchmark_inputs:
        if relative.startswith("src/"):
            input_path = source_root.joinpath(*Path(relative).parts[1:])
        else:
            input_path = root / relative
        framed_inputs.append(relative.encode("utf-8") + b"\0" + input_path.read_bytes() + b"\0")
    return {
        "revision": head or None,
        "candidate_scoped_patch_sha256": patch_hash or None,
        "candidate_scoped_patch_bytes": patch_bytes or None,
        "source_root": str(source_root),
        "package_source_tree_sha256": _package_source_tree_sha256(source_root),
        "benchmark_inputs": benchmark_inputs,
        "benchmark_inputs_sha256": hashlib.sha256(b"".join(framed_inputs)).hexdigest(),
    }


def _coverage_scope(requested_files: int, indexed_files: int, max_files: int) -> str:
    if indexed_files >= requested_files:
        return "full_fixture"
    if indexed_files >= max_files:
        return "max_files_cap"
    return "incomplete_inventory"


def _effective_impact_limit(requested_limit: int) -> int:
    return max(1, min(int(requested_limit), MAX_IMPACT_DEPENDENTS))


def _impact_coverage_status(result: dict[str, Any], *, expected: int) -> dict[str, Any]:
    coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
    complete = coverage.get("complete")
    truncated = result.get("truncated")
    if isinstance(complete, bool) and isinstance(truncated, bool):
        return {"complete": complete, "truncated": truncated, "basis": "index_coverage_metadata"}
    returned = len(result.get("likely_dependents") or [])
    return {
        "complete": returned >= expected,
        "truncated": returned < expected,
        "basis": "returned_count_vs_expected",
    }


def _process_cpu_time_seconds() -> float | None:
    try:
        measured = float(time.process_time())
    except (AttributeError, OverflowError, OSError, RuntimeError, TypeError, ValueError):
        return None
    return measured if math.isfinite(measured) and measured >= 0 else None


def _process_cpu_time_measurement(before: Any, after: Any) -> dict[str, Any]:
    delta: float | None = None
    numeric = (int, float)
    if (
        isinstance(before, numeric) and not isinstance(before, bool)
        and isinstance(after, numeric) and not isinstance(after, bool)
    ):
        try:
            start = float(before)
            end = float(after)
        except (OverflowError, TypeError, ValueError):
            pass
        else:
            if math.isfinite(start) and math.isfinite(end) and 0 <= start <= end:
                delta = end - start
    return {
        "measurement_scope": "benchmark_process_user_and_system_cpu_time",
        "measurement_basis": "time.process_time",
        "cpu_time_seconds_delta": round(delta, 4) if delta is not None else None,
    }


def _process_memory() -> dict[str, int | None]:
    if os.name == "nt":
        try:
            import psutil

            usage = psutil.Process().memory_info()
            return {
                "current_working_set_bytes": int(usage.rss),
                "peak_working_set_bytes": int(getattr(usage, "peak_wset", 0)) or None,
            }
        except Exception:
            pass

        class _MemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        try:
            counters = _MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
            if ok:
                return {
                    "current_working_set_bytes": int(counters.WorkingSetSize),
                    "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
                }
        except Exception:
            pass
        return {"current_working_set_bytes": None, "peak_working_set_bytes": None}

    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            peak *= 1024
        return {"current_working_set_bytes": None, "peak_working_set_bytes": peak}
    except Exception:
        return {"current_working_set_bytes": None, "peak_working_set_bytes": None}


class _TimedCursor:
    def __init__(self, cursor: Any, recorder: "_SqlRecorder") -> None:
        self._cursor = cursor
        self._recorder = recorder

    def _timed(self, operation: str, *args: Any) -> Any:
        started = time.perf_counter()
        try:
            return getattr(self._cursor, operation)(*args)
        finally:
            self._recorder.record(operation, time.perf_counter() - started)

    def fetchall(self) -> Any:
        return self._timed("fetchall")

    def fetchone(self) -> Any:
        return self._timed("fetchone")

    def fetchmany(self, size: int | None = None) -> Any:
        return self._timed("fetchmany", *(() if size is None else (size,)))

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _SqlRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.seconds = 0.0
        self.by_operation: dict[str, dict[str, Any]] = {}

    def record(self, operation: str, elapsed: float) -> None:
        with self._lock:
            self.calls += 1
            self.seconds += elapsed
            entry = self.by_operation.setdefault(operation, {"calls": 0, "seconds": 0.0, "samples_ms": []})
            entry["calls"] = int(entry["calls"]) + 1
            entry["seconds"] = float(entry["seconds"]) + elapsed
            entry["samples_ms"].append(elapsed * 1000)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls,
                "cumulative_ms": round(self.seconds * 1000, 4),
                "by_operation": {
                    key: {
                        "calls": int(value["calls"]),
                        "cumulative_ms": round(float(value["seconds"]) * 1000, 4),
                        "latency": _summary([float(sample) for sample in value["samples_ms"]]),
                    }
                    for key, value in sorted(self.by_operation.items())
                },
            }


class _TimedConnection:
    def __init__(self, connection: Any, recorder: _SqlRecorder) -> None:
        self._connection = connection
        self._recorder = recorder

    def _timed(self, operation: str, *args: Any) -> Any:
        started = time.perf_counter()
        try:
            result = getattr(self._connection, operation)(*args)
            if operation in {"execute", "executemany"}:
                return _TimedCursor(result, self._recorder)
            return result
        finally:
            self._recorder.record(operation, time.perf_counter() - started)

    def execute(self, *args: Any) -> _TimedCursor:
        return self._timed("execute", *args)

    def executemany(self, *args: Any) -> _TimedCursor:
        return self._timed("executemany", *args)

    def commit(self) -> Any:
        return self._timed("commit")

    def rollback(self) -> Any:
        return self._timed("rollback")

    def close(self) -> Any:
        return self._connection.close()

    def __enter__(self) -> "_TimedConnection":
        self._connection.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._connection.__exit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def _write_fixture_repo(root: Path, count: int) -> list[str]:
    paths: list[str] = []
    source_root = root / "src"
    source_root.mkdir(parents=True)
    for number in range(count):
        rel = f"src/module_{number:06d}.py"
        body = f"def caller_{number:06d}():\n    return shared_target()\n"
        if number == 0:
            body += "\ndef shared_target():\n    return 1\n"
        (root / rel).write_text(body, encoding="utf-8", newline="\n")
        paths.append(rel)
        if count >= 10_000 and (number + 1) % 10_000 == 0:
            print(f"T10 benchmark: generated {number + 1:,}/{count:,} files", flush=True)
    return paths


def _timed_call(callback, repeats: int) -> list[float]:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        callback()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def _measure_path_hint_ranking(
    groups: dict[str, list[str]], *, relevant_paths: set[str], repeats: int, limit: int = 24,
) -> dict[str, Any]:
    if repeats < 1 or limit < 1:
        raise ValueError("path-hint repeats and limit must be positive")
    rank = lambda: fuse_ranked_paths(groups, limit=limit, max_per_path=2)
    ranked = rank()
    samples = _timed_call(rank, repeats)
    paths = [path for path, _score in ranked]
    return {
        "latency": _summary_with_samples(samples),
        "outcome": {
            "success": bool(paths),
            "input_path_counts": {name: len(paths) for name, paths in sorted(groups.items())},
            "ranked_paths": paths[:limit],
            "quality": _ranking_metrics(paths, relevant_paths, k=min(10, max(1, len(paths)))),
        },
    }


SEARCH_FALLBACK_FILE_CAP = 1000


def _run_case(
    file_count: int,
    cold_repeats: int,
    warm_repeats: int,
    graph_repeats: int,
    parent: Path,
    parser_runtime: dict[str, Any],
    lookup_repeats: int = 30,
    concurrency_levels: tuple[int, ...] = (1, 4, 16, 32),
    concurrency_repeats: int = 1000,
    max_files_override: int | None = None,
    search_fallback_max_files_override: int | None = None,
) -> dict[str, Any]:
    cpu_time_before = _process_cpu_time_seconds()
    memory_before = _process_memory()
    case_root = parent / f"repo-{file_count}"
    state_dir = parent / f"state-{file_count}"
    fixture_paths = _write_fixture_repo(case_root, file_count)
    search_max_files = 8000 if max_files_override is None else max_files_override
    search_fallback_max_files = min(
        search_max_files,
        SEARCH_FALLBACK_FILE_CAP if search_fallback_max_files_override is None else search_fallback_max_files_override,
    )
    config = {"server": {"state_dir": str(state_dir)}, "search": {"max_files": search_max_files}}
    repo_tools = RepositoryTools(config)
    search_tools = RepositoryTools({
        "server": {"state_dir": str(state_dir / "bounded-search")},
        "search": {
            "max_files": search_fallback_max_files,
            "prefer_git_files": False,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
        },
    })
    full_search_tools = RepositoryTools({
        "server": {"state_dir": str(state_dir / "full-coverage-search")},
        "search": {
            "max_files": search_max_files,
            "prefer_git_files": False,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
        },
    })
    sql_recorder = _SqlRecorder()

    scan_cold: list[float] = []
    cold_inventory: dict[str, Any] | None = None
    for repeat in range(cold_repeats):
        scanner = repo_tools if repeat == 0 else RepositoryTools(config)
        cold_started = time.perf_counter()
        inventory = scanner.file_inventory(str(case_root), include_hashes=True)
        scan_cold.append((time.perf_counter() - cold_started) * 1000)
        if cold_inventory is None:
            cold_inventory = inventory
        elif inventory.get("inventory_sha256") != cold_inventory.get("inventory_sha256"):
            raise RuntimeError(f"cold file inventory mismatch for {file_count} files")
    scan_warm = _timed_call(lambda: repo_tools.file_inventory(str(case_root), include_hashes=True), warm_repeats)
    warm_inventory = repo_tools.file_inventory(str(case_root), include_hashes=True)
    assert cold_inventory is not None
    if cold_inventory.get("inventory_sha256") != warm_inventory.get("inventory_sha256"):
        raise RuntimeError(f"file inventory mismatch for {file_count} files")
    inventory_items = cold_inventory.get("files", [])
    index_items = [(str(item["path"]), str(item["sha256"])) for item in inventory_items if item.get("path") and item.get("sha256")]
    indexed_input_count = len(index_items)
    inventory_truncated = indexed_input_count < file_count

    parse_samples: list[float] = []
    parse_lock = threading.Lock()
    index_build_samples: list[float] = []
    index: CodeIndex | None = None
    indexed: dict[str, Any] = {}
    for repeat in range(cold_repeats):
        index_config = {"server": {"state_dir": str(state_dir / f"cold-{repeat + 1}")}}
        index = CodeIndex(index_config, repo_tools=repo_tools)
        raw_connect = index._connect
        index._connect = lambda raw=raw_connect: _TimedConnection(raw(), sql_recorder)  # type: ignore[method-assign]
        report_parser = getattr(index, "_parse_file_content_report", None)
        if callable(report_parser):
            raw_parse = report_parser
            parse_method = "_parse_file_content_report"
        else:
            raw_parse = index._parse_file_content
            parse_method = "_parse_file_content"

        def timed_parse(source: str, language: str, parser=raw_parse):
            started = time.perf_counter()
            try:
                return parser(source, language)
            finally:
                elapsed = (time.perf_counter() - started) * 1000
                with parse_lock:
                    parse_samples.append(elapsed)

        if parse_method == "_parse_file_content_report":
            index._parse_file_content_report = timed_parse  # type: ignore[method-assign]
        else:
            index._parse_file_content = timed_parse  # type: ignore[method-assign]
        batch_started = time.perf_counter()
        indexed = index.update_files_batch(str(case_root), index_items)
        index_build_samples.append((time.perf_counter() - batch_started) * 1000)
        if indexed.get("success") is not True:
            raise RuntimeError(f"index build failed for {file_count} files: {indexed}")
    assert index is not None
    index_build_sql = sql_recorder.snapshot()
    warm_reindex_samples = _timed_call(lambda: index.update_files_batch(str(case_root), index_items), warm_repeats)
    warm_reindex = index.update_files_batch(str(case_root), index_items)

    status_samples: list[float] = []
    for _ in range(warm_repeats):
        index._status_cache.pop(str(case_root.resolve()), None)
        status_samples.extend(_timed_call(lambda: index.status(str(case_root)), 1))

    has_callers_api = callable(getattr(index, "find_callers", None))
    has_callees_api = callable(getattr(index, "find_callees", None))
    graph_samples: dict[str, list[float]] = {
        "find_callers_default_limit": [],
        "find_callers_max_limit": [],
        "find_callees": [],
        "impact": [],
        "impact_requested_max_limit": [],
    }
    impact_result: dict[str, Any] = {}
    impact_requested_max_result: dict[str, Any] = {}
    caller_result: dict[str, Any] = {}
    default_caller_result: dict[str, Any] = {}
    full_index_limit = max(1, indexed_input_count)
    changed_path = index_items[0][0]
    for _ in range(graph_repeats):
        if has_callers_api:
            started = time.perf_counter()
            default_caller_result = index.find_callers(str(case_root), "shared_target", limit=50)
            graph_samples["find_callers_default_limit"].append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            caller_result = index.find_callers(str(case_root), "shared_target", limit=full_index_limit)
            graph_samples["find_callers_max_limit"].append((time.perf_counter() - started) * 1000)
        if has_callees_api:
            started = time.perf_counter()
            index.find_callees(str(case_root), "caller_000000", limit=30)
            graph_samples["find_callees"].append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        impact_result = index.impact(str(case_root), [changed_path], max_dependents=100)
        graph_samples["impact"].append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        impact_requested_max_result = index.impact(str(case_root), [changed_path], max_dependents=full_index_limit)
        graph_samples["impact_requested_max_limit"].append((time.perf_counter() - started) * 1000)

    symbol_query = lambda: index.find_symbol(str(case_root), "shared_target", limit=30)
    code_index_query = lambda: index.query(str(case_root), "shared_target", limit=30)
    repository_search_query = "caller_000000"
    repository_query = lambda: search_tools.search(str(case_root), repository_search_query, limit=12)
    full_repository_query = lambda: full_search_tools.search(str(case_root), repository_search_query, limit=12)
    symbol_query()
    repository_cold_started = time.perf_counter()
    repository_cold_search_result = repository_query()
    repository_cold_latency_ms = (time.perf_counter() - repository_cold_started) * 1000
    symbol_lookup_result = symbol_query()
    symbol_lookup_samples = _timed_call(symbol_query, lookup_repeats)
    code_index_query_started = time.perf_counter()
    code_index_query_result = code_index_query()
    code_index_query_cold_latency_ms = (time.perf_counter() - code_index_query_started) * 1000
    code_index_query_samples = _timed_call(code_index_query, lookup_repeats)
    repository_search_result = repository_query()
    repository_search_samples = _timed_call(repository_query, lookup_repeats)
    full_search_cold_started = time.perf_counter()
    full_search_cold_result = full_repository_query()
    full_search_cold_latency_ms = (time.perf_counter() - full_search_cold_started) * 1000
    full_search_repeats = min(max(1, lookup_repeats), 30)
    full_search_result = full_repository_query()
    full_search_samples = _timed_call(full_repository_query, full_search_repeats)
    accelerator_started = time.perf_counter()
    accelerator_search_result = repo_tools.search(str(case_root), repository_search_query, limit=12)
    accelerator_search_latency_ms = (time.perf_counter() - accelerator_started) * 1000
    callers_quality_result = index.find_callers(str(case_root), "shared_target", limit=10)
    path_hint_groups = {
        "deterministic": [
            str(item.get("path") or "") for item in symbol_lookup_result.get("symbols", [])
            if item.get("path")
        ],
        "code_index": [
            str(item.get("path") or "") for item in caller_result.get("callers", [])[:24]
            if item.get("path")
        ],
        "lexical": [
            str(item.get("path") or "") for item in full_search_result.get("results", [])
            if item.get("path")
        ],
    }
    path_hint_ranking = _measure_path_hint_ranking(
        path_hint_groups,
        relevant_paths={"src/module_000000.py"},
        repeats=lookup_repeats,
        limit=24,
    )

    concurrency_workloads: dict[str, Any] = {}
    for worker_count in concurrency_levels:
        concurrency_workloads[str(worker_count)] = {
            "find_callers": (
                _measure_concurrent_workload(
                    lambda: index.find_callers(str(case_root), "shared_target", limit=50),
                    workers=worker_count,
                    sample_count=concurrency_repeats,
                )
                if has_callers_api else None
            ),
            "impact": _measure_concurrent_workload(
                lambda: index.impact(str(case_root), [changed_path], max_dependents=100),
                workers=worker_count,
                sample_count=concurrency_repeats,
            ),
        }

    edge_status = index.status(str(case_root))
    observed_caller_edges = edge_status.get("edges")
    if observed_caller_edges is not None:
        observed_caller_edges = int(observed_caller_edges)
    impact_coverage = impact_result.get("coverage") or {}
    expected_impact_dependents = max(0, indexed_input_count - 1)
    default_impact_status = _impact_coverage_status(impact_result, expected=expected_impact_dependents)
    requested_max_impact_status = _impact_coverage_status(
        impact_requested_max_result, expected=expected_impact_dependents,
    )
    graph_coverage = {
        "caller_graph_api_available": has_callers_api,
        "callee_graph_api_available": has_callees_api,
        "expected_caller_edges_in_index": indexed_input_count,
        "indexed_caller_edges": observed_caller_edges if has_callers_api else None,
        "default_limit": 50 if has_callers_api else None,
        "default_limit_observed": int(default_caller_result.get("count", 0)) if has_callers_api else None,
        "default_limit_truncated": default_caller_result.get("truncated") if has_callers_api else None,
        "default_limit_coverage_ratio": round(int(default_caller_result.get("count", 0)) / max(1, indexed_input_count), 4) if has_callers_api else None,
        "full_index_limit": full_index_limit if has_callers_api else None,
        "full_index_observed": int(caller_result.get("count", 0)) if has_callers_api else None,
        "full_index_truncated": caller_result.get("truncated") if has_callers_api else None,
        "full_index_coverage_ratio": round(int(caller_result.get("count", 0)) / max(1, indexed_input_count), 4) if has_callers_api else None,
        "caller_query_truncated": caller_result.get("truncated") if has_callers_api else None,
        "caller_query_coverage_complete": (caller_result.get("coverage") or {}).get("complete") if has_callers_api else None,
        "caller_freshness": (caller_result.get("freshness") or {}).get("status") if has_callers_api else "unsupported",
        "impact_expected_dependent_paths": expected_impact_dependents,
        "impact_dependent_candidates_observed": impact_coverage.get(
            "dependent_candidate_count", len(impact_result.get("likely_dependents") or [])
        ),
        "impact_candidate_count_exact": impact_coverage.get("dependent_candidate_count_exact"),
        "impact_freshness": (impact_result.get("freshness") or {}).get("status"),
        "impact_truncated": default_impact_status["truncated"],
        "impact_coverage_complete": default_impact_status["complete"],
        "impact_coverage_basis": default_impact_status["basis"],
        "impact_requested_dependents": full_index_limit,
        "impact_effective_dependents_cap": _effective_impact_limit(full_index_limit),
        "impact_requested_max_dependents_observed": len(impact_requested_max_result.get("likely_dependents") or []),
        "impact_requested_max_candidate_count_exact": (impact_requested_max_result.get("coverage") or {}).get("dependent_candidate_count_exact"),
        "impact_requested_max_truncated": requested_max_impact_status["truncated"],
        "impact_requested_max_coverage_complete": requested_max_impact_status["complete"],
        "impact_requested_max_coverage_basis": requested_max_impact_status["basis"],
    }
    target_path = "src/module_000000.py"
    target_line = 4
    search_target_line = 1
    target_callers = {str(path) for path, _content_hash in index_items}
    changed_path_normalized = changed_path.replace("\\", "/").strip("/")
    impact_paths = {path for path in target_callers if path.replace("\\", "/").strip("/") != changed_path_normalized}
    symbol_evidence = [
        (str(symbol.get("path") or ""), int(symbol["line"]))
        for symbol in symbol_lookup_result.get("symbols", [])
        if symbol.get("line") is not None
    ]
    caller_evidence = [
        (str(caller.get("path") or ""), int(caller["line"]))
        for caller in callers_quality_result.get("callers", [])
        if caller.get("line") is not None
    ]
    full_caller_evidence = {
        (str(caller.get("path") or ""), int(caller["line"]))
        for caller in caller_result.get("callers", [])
        if caller.get("line") is not None
    }
    expected_caller_evidence = {(path, 2) for path in target_callers}
    matched_caller_evidence = full_caller_evidence & expected_caller_evidence
    impact_evidence = [
        (str(dependent.get("path") or ""),)
        for dependent in impact_result.get("likely_dependents", [])
    ]
    full_impact_evidence = {
        str(dependent.get("path") or "")
        for dependent in impact_requested_max_result.get("likely_dependents", [])
    }
    matched_impact_evidence = full_impact_evidence & impact_paths
    quality_metrics = {
        "corpus": "synthetic_python_call_graph",
        "k": 10,
        "evidence_scope": "relative_path_and_line_for_symbol_search_callers; relative_path_for_impact",
        "path_hint_ranking": path_hint_ranking["outcome"]["quality"],
        "symbol_lookup": _ranking_metrics(symbol_evidence, {(target_path, target_line)}),
        "code_index_query_file_line": _ranking_metrics(
            [
                (str(symbol.get("path") or ""), int(symbol["line"]))
                for symbol in code_index_query_result.get("symbols", [])
                if symbol.get("line") is not None
            ],
            {(target_path, target_line)},
        ),
        "repository_search_file_line": _ranking_metrics(
            _search_line_evidence(repository_search_result.get("results", []), repository_search_query),
            {(target_path, search_target_line)},
        ),
        "repository_search_full_coverage_file_line": _ranking_metrics(
            _search_line_evidence(full_search_result.get("results", []), repository_search_query),
            {(target_path, search_target_line)},
        ),
        "repository_search_accelerator_probe_file_line": _ranking_metrics(
            _search_line_evidence(accelerator_search_result.get("results", []), repository_search_query),
            {(target_path, search_target_line)},
        ),
        "find_callers_file_line": _ranking_metrics(
            caller_evidence,
            expected_caller_evidence,
        ),
        "find_callers_full_coverage": {
            "expected_count": len(expected_caller_evidence),
            "returned_count": len(caller_result.get("callers") or []),
            "matched_count": len(matched_caller_evidence),
            "coverage_recall": round(len(matched_caller_evidence) / max(1, len(expected_caller_evidence)), 4),
            "complete": (caller_result.get("coverage") or {}).get("complete") is True,
            "truncated": caller_result.get("truncated"),
        },
        "impact_file": _ranking_metrics(
            impact_evidence,
            {(path,) for path in impact_paths},
        ),
        "impact_requested_max_limit": {
            "requested_limit": full_index_limit,
            "effective_limit": _effective_impact_limit(full_index_limit),
            "expected_count": len(impact_paths),
            "returned_count": len(impact_requested_max_result.get("likely_dependents") or []),
            "matched_count": len(matched_impact_evidence),
            "coverage_recall": round(len(matched_impact_evidence) / max(1, len(impact_paths)), 4),
            "complete": _impact_coverage_status(
                impact_requested_max_result, expected=len(impact_paths),
            )["complete"],
            "truncated": _impact_coverage_status(
                impact_requested_max_result, expected=len(impact_paths),
            )["truncated"],
        },
    }
    indexed_counts = {key: edge_status.get(key) for key in ("files", "symbols", "refs", "edges")}
    index_coverage = {
        "requested_fixture_files": file_count,
        "inventory_reported_files": indexed_input_count,
        "inventory_truncated": inventory_truncated,
        "inventory_coverage_ratio": round(indexed_input_count / max(1, file_count), 4),
        "expected_indexed_files": indexed_input_count,
        "observed_files": indexed_counts.get("files"),
        "files_complete": indexed_counts.get("files") == indexed_input_count,
        "expected_call_edges": indexed_input_count if has_callers_api else None,
        "observed_call_edges": indexed_counts.get("edges"),
        "call_edges_complete": indexed_counts.get("edges") == indexed_input_count if has_callers_api else None,
    }
    parse_outcomes = indexed.get("parse_outcomes", {})
    memory_after = _process_memory()
    cpu_time_after = _process_cpu_time_seconds()
    peak_before = memory_before.get("peak_working_set_bytes")
    peak_after = memory_after.get("peak_working_set_bytes")
    return {
        "requested_fixture_files": file_count,
        "indexed_files": indexed_input_count,
        "coverage_mode": _coverage_scope(file_count, indexed_input_count, repo_tools.max_files),
        "source_bytes": sum((case_root / path).stat().st_size for path in fixture_paths),
        "quality": quality_metrics,
        "scan": {
            "configured_max_files": repo_tools.max_files,
            "coverage": {
                "complete": not inventory_truncated,
                "requested_fixture_files": file_count,
                "observed_files": indexed_input_count,
                "truncated": inventory_truncated,
                "ratio": round(indexed_input_count / max(1, file_count), 4),
            },
            "cold": _summary_with_samples(scan_cold),
            "warm": _summary_with_samples(scan_warm),
        },
        "parse": {
            "instrumented_method": parse_method,
            "files": len(parse_samples),
            "per_file_latency": _summary_with_samples(parse_samples),
            "index_build_wall": _summary_with_samples(index_build_samples),
            "index_build_wall_ms": round(statistics.fmean(index_build_samples), 4),
            "warm_reindex": _summary_with_samples(warm_reindex_samples),
            "warm_reindex_files_processed": warm_reindex.get("files_processed"),
            "warm_reindex_cache_hits": warm_reindex.get("cached"),
            "parse_outcomes": {key: value for key, value in parse_outcomes.items() if key != "diagnostics"},
        },
        "sqlite": {
            "status_count_query": _summary_with_samples(status_samples),
            "index_build_sql": index_build_sql,
            "instrumented_calls_during_index_and_graph": sql_recorder.snapshot(),
            "indexed_rows": indexed_counts,
            "coverage": index_coverage,
        },
        "lookups": {
            "repeats": lookup_repeats,
            "find_symbol": {
                "latency": _summary_with_samples(symbol_lookup_samples),
                "outcome": {
                    "success": symbol_lookup_result.get("success") is True,
                    "symbols_found": len(symbol_lookup_result.get("symbols") or []),
                    "truncated": symbol_lookup_result.get("truncated"),
                },
            },
            "code_index_query": {
                "query": "shared_target",
                "cache_state": "warm_query_l1_after_first_call",
                "cold_latency_ms": round(code_index_query_cold_latency_ms, 4),
                "latency": _summary_with_samples(code_index_query_samples),
                "outcome": {
                    "success": code_index_query_result.get("success") is True,
                    "symbols_found": len(code_index_query_result.get("symbols") or []),
                    "truncated": code_index_query_result.get("truncated"),
                    "confidence": code_index_query_result.get("confidence"),
                    "query_term_coverage": (code_index_query_result.get("coverage") or {}).get("query_term_coverage"),
                },
            },
            "path_hint_ranking": path_hint_ranking,
            "repository_search": {
                "query": repository_search_query,
                "mode": "capped_python_fallback",
                "cache_state": "warm_file_snapshot_cache",
                "scan_cap": {
                    "max_files": search_fallback_max_files,
                    "fixture_files": file_count,
                },
                "cold_latency_ms": round(repository_cold_latency_ms, 4),
                "cold_outcome": {
                    "success": repository_cold_search_result.get("success") is True,
                    "results_found": len(repository_cold_search_result.get("results") or []),
                    "scanned_files": repository_cold_search_result.get("scanned_files"),
                    "coverage_complete": repository_cold_search_result.get("scanned_files", 0) >= file_count,
                    "engine": repository_cold_search_result.get("engine"),
                },
                "latency": _summary_with_samples(repository_search_samples),
                "outcome": {
                    "success": repository_search_result.get("success") is True,
                    "results_found": len(repository_search_result.get("results") or []),
                    "scanned_files": repository_search_result.get("scanned_files"),
                    "coverage_complete": repository_search_result.get("scanned_files", 0) >= file_count,
                    "engine": repository_search_result.get("engine"),
                },
            },
            "repository_search_full_coverage": {
                "query": repository_search_query,
                "mode": "full_coverage_python_fallback",
                "max_files": search_max_files,
                "fixture_files": file_count,
                "repeats": full_search_repeats,
                "cold_latency_ms": round(full_search_cold_latency_ms, 4),
                "cold_outcome": {
                    "success": full_search_cold_result.get("success") is True,
                    "results_found": len(full_search_cold_result.get("results") or []),
                    "scanned_files": full_search_cold_result.get("scanned_files"),
                    "coverage_complete": full_search_cold_result.get("scanned_files", 0) >= file_count,
                    "engine": full_search_cold_result.get("engine"),
                },
                "latency": _summary_with_samples(full_search_samples),
                "outcome": {
                    "success": full_search_result.get("success") is True,
                    "results_found": len(full_search_result.get("results") or []),
                    "scanned_files": full_search_result.get("scanned_files"),
                    "coverage_complete": full_search_result.get("scanned_files", 0) >= file_count,
                    "engine": full_search_result.get("engine"),
                },
            },
            "repository_search_accelerator_probe": {
                "attempted": True,
                "query": repository_search_query,
                "mode": "default_accelerator_probe",
                "ripgrep_timeout_budget_seconds": repo_tools.ripgrep_timeout,
                "git_grep_timeout_budget_seconds": repo_tools.git_grep_timeout,
                "latency_ms": round(accelerator_search_latency_ms, 4),
                "stats": {
                    key: repo_tools._git_stats[key]
                    for key in (
                        "ripgrep_timeouts",
                        "ripgrep_cooldown_skips",
                        "grep_timeouts",
                        "grep_cooldown_skips",
                    )
                },
                "outcome": {
                    "success": accelerator_search_result.get("success") is True,
                    "results_found": len(accelerator_search_result.get("results") or []),
                    "scanned_files": accelerator_search_result.get("scanned_files"),
                    "engine": accelerator_search_result.get("engine"),
                    "error": accelerator_search_result.get("error"),
                    "retryable": accelerator_search_result.get("retryable"),
                },
            },
        },
        "graph": {
            "repeats": graph_repeats,
            "latency": {name: _summary_with_samples(samples) for name, samples in graph_samples.items()},
            "coverage": graph_coverage,
            "concurrency": {
                "sample_count_per_workload": concurrency_repeats,
                "worker_levels": list(concurrency_levels),
                "cache_state": "warm_after_sequential_graph_queries",
                "measurement_method": "bounded_thread_pool; latency starts after worker release and includes index-lock wait",
                "workloads": concurrency_workloads,
            },
        },
        "backend_contract": {
            "built_in_code_index": "measured",
            "path_hint_ranking": "bounded_deterministic_code_index_lexical_reciprocal_rank_fusion",
            "repository_search": f"capped_python_fallback; max_files={search_fallback_max_files}; ripgrep_and_git_grep_disabled",
            "repository_search_full_coverage": f"full_coverage_python_fallback; max_files={search_max_files}; ripgrep_and_git_grep_disabled",
            "repository_search_accelerator_probe": "one_default_search_attempt; engine_and_bounded_failure_reported",
            "fixture_language": "python",
            **parser_runtime,
            "serena": "not_invoked_by_repository_benchmark",
        },
        "cpu": _process_cpu_time_measurement(cpu_time_before, cpu_time_after),
        "memory": {
            "measurement_scope": "process_lifetime_high_water_mark",
            "current_working_set_before_case_bytes": memory_before.get("current_working_set_bytes"),
            "current_working_set_after_case_bytes": memory_after.get("current_working_set_bytes"),
            "peak_working_set_before_case_bytes": peak_before,
            "peak_working_set_through_case_bytes": peak_after,
            "peak_increase_during_case_bytes": max(0, peak_after - peak_before)
            if peak_before is not None and peak_after is not None else None,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", nargs="+", type=int, default=[100, 10_000, 100_000])
    parser.add_argument("--parser-backend", choices=("auto", "fallback"), default="auto")
    parser.add_argument("--cold-repeats", type=int, default=5)
    parser.add_argument("--warm-repeats", type=int, default=30)
    parser.add_argument("--graph-repeats", type=int, default=30)
    parser.add_argument("--lookup-repeats", type=int, default=30)
    parser.add_argument("--concurrency-levels", nargs="+", type=int, default=[1, 4, 16, 32])
    parser.add_argument("--concurrency-repeats", type=int, default=1000)
    parser.add_argument("--max-files", type=int, default=0, help="override repository file cap; 0 uses product default")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (
        any(value < 1 for value in args.files)
        or min(args.cold_repeats, args.warm_repeats, args.graph_repeats, args.lookup_repeats, args.concurrency_repeats) < 1
        or not args.concurrency_levels
        or any(value < 1 for value in args.concurrency_levels)
        or len(set(args.concurrency_levels)) != len(args.concurrency_levels)
        or args.concurrency_repeats < max(args.concurrency_levels)
        or args.max_files < 0
    ):
        parser.error("file sizes and repeat counts must be positive")

    results: list[dict[str, Any]] = []
    source_identity = _source_identity()
    parser_runtime = _configure_parser_backend(args.parser_backend)
    with tempfile.TemporaryDirectory(prefix="t10-repository-benchmark-") as scratch:
        scratch_path = Path(scratch)
        for size in args.files:
            print(f"T10 benchmark: starting {size:,} files", flush=True)
            result = _run_case(
                size,
                args.cold_repeats,
                args.warm_repeats,
                args.graph_repeats,
                scratch_path,
                parser_runtime,
                lookup_repeats=args.lookup_repeats,
                concurrency_levels=tuple(args.concurrency_levels),
                concurrency_repeats=args.concurrency_repeats,
                max_files_override=args.max_files or None,
            )
            results.append(result)
            print(f"T10 benchmark: finished {size:,} files", flush=True)
            record = {
                "schema_version": 1,
                "benchmark": "t10_repository_scan_parse_sql_graph",
                "source": source_identity,
                "benchmark_settings": {
                    "cold_repeats": args.cold_repeats,
                    "warm_repeats": args.warm_repeats,
                    "graph_repeats": args.graph_repeats,
                    "lookup_repeats": args.lookup_repeats,
                    "concurrency_levels": args.concurrency_levels,
                    "concurrency_repeats": args.concurrency_repeats,
                    "max_files_override": args.max_files or None,
                    "parser_runtime": parser_runtime,
                },
                "environment": {
                    "python": sysconfig.get_python_version(),
                    "platform": platform.platform(),
                    "logical_cpus": os.cpu_count(),
                },
                "matrix": results,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({"output": str(args.output.resolve()), "completed_sizes": args.files}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
