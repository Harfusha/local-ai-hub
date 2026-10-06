"""Reproducible, bounded performance probe for CommandBroker hot paths."""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import datetime as dt
import hashlib
import importlib
import json
import os
import platform
import random
import shutil
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from local_ai_hub.commands import CommandBroker

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


SCHEMA = "t15-command-broker-benchmark-v2"
COMMAND = "git status --short"
SINGLEFLIGHT_COMMAND = (
    f"{subprocess.list2cmdline([sys.executable])} -c \"import time; time.sleep(2.0)\""
    if os.name == "nt"
    else f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(2.0)'"
)
CONCURRENCY_LEVELS = (1, 4, 16, 32)


def _nearest_rank(samples: list[float], percentile: int) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, (percentile * len(ordered) + 99) // 100 - 1))
    return round(ordered[index], 3)


def _summary(samples: list[float]) -> dict[str, Any]:
    if not samples:
        raise ValueError("benchmark produced no samples")
    return {
        "n": len(samples),
        "unit": "ms",
        "p50": _nearest_rank(samples, 50),
        "p95": _nearest_rank(samples, 95),
        "p99": _nearest_rank(samples, 99),
        "min": round(min(samples), 3),
        "max": round(max(samples), 3),
        "raw": [round(sample, 3) for sample in samples],
    }


def _first_and_repeated(samples: list[float]) -> dict[str, Any]:
    return {
        "first_call_ms": round(samples[0], 3),
        "repeated_calls": _summary(samples[1:]) if len(samples) > 1 else None,
    }


def _pair_orders(paired_runs: int, *, seed: int) -> list[tuple[str, str]]:
    if paired_runs < 1:
        raise ValueError("paired_runs must be positive")
    orders = [("hit", "miss") for _ in range((paired_runs + 1) // 2)]
    orders.extend(("miss", "hit") for _ in range(paired_runs // 2))
    random.Random(seed).shuffle(orders)
    return orders


def _pair_order_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for order in ("hit_then_miss", "miss_then_hit"):
        selected = [row for row in rows if row.get("order") == order]
        if selected:
            result[order] = {
                "n": len(selected),
                "cache_hit": _summary([float(row["hit_ms"]) for row in selected]),
                "cache_miss": _summary([float(row["miss_ms"]) for row in selected]),
            }
    return result


def _broker_shell_path(*, windows: bool | None = None) -> str:
    use_windows = os.name == "nt" if windows is None else windows
    if use_windows:
        return shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    return shutil.which("sh") or "/bin/sh"


def _git_identity(root: Path) -> dict[str, Any]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
        text=True, timeout=5, check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True,
        text=True, timeout=5, check=True,
    ).stdout.strip()
    return {"head": head, "dirty": bool(dirty)}


def _load_command_api(source_root: Path) -> tuple[Callable[..., str], type]:
    source_root = source_root.resolve(strict=True)
    source_path = source_root / "src"
    sys.path.insert(0, str(source_path))
    cache_module = importlib.import_module("local_ai_hub.cache")
    commands_module = importlib.import_module("local_ai_hub.commands")
    commands_path = Path(commands_module.__file__).resolve()
    if source_root not in commands_path.parents:
        raise RuntimeError("CommandBroker import did not resolve inside --root")
    return cache_module.stable_hash, commands_module.CommandBroker


def _measure_cache_pairs(
    broker: CommandBroker,
    root: str,
    *,
    paired_runs: int,
    order_seed: int,
) -> dict[str, Any]:
    tenant = "t15-benchmark"
    seed_result = broker.run(COMMAND, root, tenant=tenant, force=True)
    _require_success(seed_result, "paired cache seed")
    if _require_cache_outcome(seed_result, "paired cache seed") is not False:
        raise RuntimeError("paired cache seed must report an observed miss")

    pairs: list[dict[str, Any]] = []
    for operations in _pair_orders(paired_runs, seed=order_seed):
        pair = {"order": f"{operations[0]}_then_{operations[1]}"}
        for operation in operations:
            force = operation == "miss"
            elapsed, result = _timed(
                lambda force=force: broker.run(
                    COMMAND, root, tenant=tenant, force=force
                )
            )
            _require_success(result, f"paired cache {operation}")
            cache_hit = _require_cache_outcome(result, f"paired cache {operation}")
            expected_hit = operation == "hit"
            if cache_hit is not expected_hit:
                raise RuntimeError(f"paired cache {operation} returned unexpected cache outcome")
            pair[f"{operation}_cache_hit"] = cache_hit
            pair[f"{operation}_ms"] = elapsed
        pairs.append(pair)

    hit_samples = [float(pair["hit_ms"]) for pair in pairs]
    miss_samples = [float(pair["miss_ms"]) for pair in pairs]
    observed_hits = sum(pair["hit_cache_hit"] is True for pair in pairs)
    observed_misses = sum(pair["miss_cache_hit"] is False for pair in pairs)
    if observed_hits != paired_runs or observed_misses != paired_runs:
        raise RuntimeError("paired cache accounting did not match requested hit/miss samples")
    reductions = [
        (miss - hit) * 100.0 / miss if miss > 0 else 0.0
        for hit, miss in zip(hit_samples, miss_samples)
    ]
    orders = _pair_orders(paired_runs, seed=order_seed)
    return {
        "orders": orders,
        "pairs": pairs,
        "hit_samples": hit_samples,
        "miss_samples": miss_samples,
        "reductions_pct": reductions,
        "order_summary": _pair_order_summary(pairs),
        "fixture": {
            "command": COMMAND,
            "tenant": tenant,
            "forced_seed_cache_hit": False,
            "seed_counted_in_pairs": False,
            "paired_runs": paired_runs,
            "pair_order_seed": order_seed,
            "order_counts": {
                "hit_then_miss": sum(order == ("hit", "miss") for order in orders),
                "miss_then_hit": sum(order == ("miss", "hit") for order in orders),
            },
        },
        "cache_accounting": {
            "paired_operations": paired_runs * 2,
            "expected_hits": paired_runs,
            "observed_hits": observed_hits,
            "expected_misses": paired_runs,
            "observed_misses": observed_misses,
            "classification_complete": True,
            "seed_miss_counted": False,
        },
    }


def _seed_concurrency_cache(broker: CommandBroker, root: str) -> dict[str, Any]:
    seed = broker.run(COMMAND, root, tenant="t15-benchmark")
    _require_success(seed, "concurrency cache seed")
    if _require_cache_outcome(seed, "concurrency cache seed") is not False:
        raise RuntimeError("concurrency cache seed did not report a cache miss")
    return seed


def _source_snapshot(root: Path) -> dict[str, Any]:
    source_path = root / "src" / "local_ai_hub" / "commands.py"
    script_path = Path(__file__).resolve()
    return {
        **_git_identity(root),
        "commands_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "benchmark_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
    }


def _validate_revision_match(
    source: dict[str, Any],
    execution_root: dict[str, Any],
) -> None:
    if source["dirty"] or execution_root["dirty"]:
        raise RuntimeError("revision-matched benchmark requires clean source and execution checkouts")
    if source["head"] != execution_root["head"]:
        raise RuntimeError("source and execution root must use the same pinned revision")


def _total_memory_bytes() -> int | None:
    try:
        if os.name == "nt":
            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
            return None
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _command_version(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return next((line.strip()[:160] for line in result.stdout.splitlines() if line.strip()), None)


def _timed(operation: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = operation()
    return (time.perf_counter() - started) * 1000.0, result


def _python_command(code: str) -> str:
    argv = [sys.executable, "-c", code]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _require_success(result: dict[str, Any], operation: str) -> None:
    if result.get("success") is not True:
        raise RuntimeError(f"{operation} failed: {result.get('error', 'unknown error')}")


def _require_cache_outcome(result: dict[str, Any], operation: str) -> bool:
    cache_hit = result.get("cache_hit")
    if not isinstance(cache_hit, bool):
        raise RuntimeError(f"{operation} did not report a boolean cache outcome")
    return cache_hit


def _concurrent_cache_sample_receipts(
    raw_results: list[tuple[float, bool]],
) -> list[dict[str, Any]]:
    return [
        {
            "sample_index": index,
            "elapsed_ms": round(elapsed, 6),
            "cache_hit": cache_hit,
        }
        for index, (elapsed, cache_hit) in enumerate(raw_results)
    ]


def _capture_sample(
    broker: CommandBroker,
    root: str,
    *,
    callback_enabled: bool = True,
) -> dict[str, Any]:
    code = (
        "import sys; "
        "[print('O' * 64) for _ in range(2000)]; "
        "[print('E' * 64, file=sys.stderr) for _ in range(2000)]"
    )
    callback_chunks: list[tuple[str, str]] = []
    started = time.perf_counter()
    result = broker._execute(
        _python_command(code),
        root,
        20,
        log_callback=(
            (lambda stream, chunk: callback_chunks.append((stream, chunk)))
            if callback_enabled
            else None
        ),
    )
    elapsed = (time.perf_counter() - started) * 1000.0
    _require_success(result, "dual-stream capture")
    if callback_enabled and (
        result.get("log_dispatch_incomplete") or result.get("log_chunks_dropped", 0)
    ):
        raise RuntimeError("dual-stream capture dropped or failed to dispatch output")
    stdout_bytes = len(result.get("stdout", "").encode("utf-8"))
    stderr_bytes = len(result.get("stderr", "").encode("utf-8"))
    callback_chars = {
        stream: sum(len(chunk.encode("utf-8")) for name, chunk in callback_chunks if name == stream)
        for stream in ("stdout", "stderr")
    }
    if stdout_bytes < 130_000 or stderr_bytes < 130_000:
        raise RuntimeError("dual-stream capture returned incomplete output")
    if callback_enabled and (
        callback_chars["stdout"] != stdout_bytes
        or callback_chars["stderr"] != stderr_bytes
    ):
        raise RuntimeError("stream callbacks did not receive complete output")
    return {
        "wall_ms": elapsed,
        "callback_enabled": callback_enabled,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "callback_chunks": len(callback_chunks),
        "callback_stdout_bytes": callback_chars["stdout"],
        "callback_stderr_bytes": callback_chars["stderr"],
        "dropped_chunks": int(result.get("log_chunks_dropped", 0)),
        "dispatch_incomplete": bool(result.get("log_dispatch_incomplete", False)),
    }


def run_benchmark(
    root: Path,
    light_samples: int,
    paired_runs: int,
    *,
    order_seed: int = 0,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    stable_hash, CommandBroker = _load_command_api(root)
    source_before = _source_snapshot(root)
    execution_root_before = _git_identity(root)
    harness_before = _git_identity(REPOSITORY_ROOT)
    if harness_before["dirty"]:
        raise RuntimeError("revision-matched benchmark requires a clean harness checkout")
    _validate_revision_match(source_before, execution_root_before)
    command_config = {
        "enabled": True,
        "allow_read": True,
        "allow_validation": True,
        "allow_build": True,
        "allow_unknown": True,
        "timeout_seconds": 20,
        "max_output_chars": 2_000_000,
    }
    config = {
        "server": {"state_dir": "<temporary benchmark state>"},
        "commands": command_config,
    }
    config_fingerprint = stable_hash(config)

    with tempfile.TemporaryDirectory(prefix="t15-command-broker-") as temp_dir:
        runtime_config = {
            **config,
            "server": {"state_dir": str(Path(temp_dir) / "state")},
        }
        broker = CommandBroker(runtime_config)

        classification_samples = []
        for _ in range(light_samples):
            elapsed, result = _timed(lambda: broker.classify(COMMAND))
            if not result.get("allowed"):
                raise RuntimeError("classification benchmark command is not allowed")
            classification_samples.append(elapsed)

        forced_fingerprint_samples = []
        for _ in range(paired_runs):
            elapsed, _ = _timed(lambda: broker.repo_state.fingerprint(str(root), force=True))
            forced_fingerprint_samples.append(elapsed)
        broker.repo_state.fingerprint(str(root), force=True)
        warm_fingerprint_samples = []
        for _ in range(light_samples):
            elapsed, _ = _timed(lambda: broker.repo_state.fingerprint(str(root)))
            warm_fingerprint_samples.append(elapsed)

        paired_cache = _measure_cache_pairs(
            broker,
            str(root),
            paired_runs=paired_runs,
            order_seed=order_seed,
        )
        paired_miss_samples = paired_cache["miss_samples"]
        paired_hit_samples = paired_cache["hit_samples"]
        pair_reductions = paired_cache["reductions_pct"]

        concurrency_broker = CommandBroker(
            {
                **config,
                "server": {"state_dir": str(Path(temp_dir) / "concurrency-state")},
            }
        )
        seed = _seed_concurrency_cache(concurrency_broker, str(root))
        concurrency_results: dict[str, Any] = {}
        for workers in CONCURRENCY_LEVELS:
            def warm_hit(_index: int) -> tuple[float, bool]:
                elapsed, result = _timed(
                    lambda: concurrency_broker.run(
                        COMMAND, str(root), tenant="t15-benchmark"
                    )
                )
                _require_success(result, "concurrent warm command")
                cache_hit = _require_cache_outcome(result, "concurrent warm command")
                return elapsed, cache_hit

            started = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                raw_results = list(pool.map(warm_hit, range(light_samples)))
            total_seconds = time.perf_counter() - started
            call_samples = [elapsed for elapsed, _cache_hit in raw_results]
            hit_count = sum(cache_hit is True for _elapsed, cache_hit in raw_results)
            miss_count = sum(cache_hit is False for _elapsed, cache_hit in raw_results)
            if hit_count != light_samples or miss_count != 0:
                raise RuntimeError(f"warm cache misses under concurrency {workers}")
            concurrency_results[str(workers)] = {
                "calls": _summary(call_samples),
                "throughput_per_second": round(light_samples / total_seconds, 3),
                "cache_hits": hit_count,
                "expected_cache_hits": light_samples,
                "observed_cache_hits": hit_count,
                "observed_cache_misses": miss_count,
                "classified_calls": hit_count + miss_count,
                "seed_cache_hit": seed["cache_hit"],
                "raw_samples": _concurrent_cache_sample_receipts(raw_results),
            }

            singleflight_batches = []
            singleflight_executed = 0
            for _ in range(paired_runs):
                barrier = threading.Barrier(workers)

                def forced_miss(_index: int) -> tuple[float, dict[str, Any]]:
                    barrier.wait(timeout=20)
                    elapsed, result = _timed(
                        lambda: broker.run(
                            SINGLEFLIGHT_COMMAND,
                            str(root),
                            tenant="t15-benchmark",
                            force=True,
                        )
                    )
                    _require_success(result, "concurrent forced command")
                    return elapsed, result

                executed_before = broker.executed
                coalesced_before = broker.coalesced
                started = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(forced_miss, index) for index in range(workers)]
                    overlap_deadline = time.monotonic() + 5.0
                    while (
                        broker.coalesced - coalesced_before < workers - 1
                        and time.monotonic() < overlap_deadline
                    ):
                        if all(future.done() for future in futures):
                            break
                        time.sleep(0.002)
                    rows = [future.result() for future in futures]
                batch_elapsed = (time.perf_counter() - started) * 1000.0
                owners = sum(not row[1].get("coalesced", False) for row in rows)
                waiters = sum(row[1].get("coalesced") is True for row in rows)
                executed_delta = broker.executed - executed_before
                if owners != 1 or waiters != workers - 1 or executed_delta != 1:
                    raise RuntimeError(
                        f"single-flight failed at concurrency {workers}: "
                        f"owners={owners}, waiters={waiters}, executions={executed_delta}"
                    )
                singleflight_executed += executed_delta
                singleflight_batches.append(batch_elapsed)
            concurrency_results[str(workers)]["singleflight_forced_batches"] = {
                "latency": _summary(singleflight_batches),
                "batches": paired_runs,
                "workers_per_batch": workers,
                "executions": singleflight_executed,
                "coalesced_waiters": paired_runs * (workers - 1),
            }

        startup_samples = []
        command = _python_command("pass")
        for _ in range(paired_runs):
            elapsed, result = _timed(
                lambda: broker._execute(
                    command, str(root), 20
                )
            )
            _require_success(result, "structured process startup")
            startup_samples.append(elapsed)

        shell_command = (
            "Write-Output t15-shell-start;"
            if os.name == "nt"
            else "printf t15-shell-start;"
        )
        shell_startup_samples = []
        for _ in range(paired_runs):
            elapsed, result = _timed(lambda: broker._execute(shell_command, str(root), 20))
            _require_success(result, "shell process startup")
            shell_startup_samples.append(elapsed)

        capture_records = [
            _capture_sample(broker, str(root), callback_enabled=True)
            for _ in range(paired_runs)
        ]
        capture_without_callback_records = [
            _capture_sample(broker, str(root), callback_enabled=False)
            for _ in range(paired_runs)
        ]

        source_after = _source_snapshot(root)
        execution_root_after = _git_identity(root)
        harness_after = _git_identity(REPOSITORY_ROOT)
        if (
            source_after != source_before
            or execution_root_after != execution_root_before
            or harness_after != harness_before
        ):
            raise RuntimeError("harness, source, or execution repository changed during benchmark")
        shell_path = _broker_shell_path()
        if os.name == "nt":
            shell_version = _command_version(
                [shell_path, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"]
            )
        else:
            shell_version = _command_version([shell_path, "--version"])
        git_version = _command_version(["git", "--version"])
        return {
            "schema": SCHEMA,
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "success": True,
            "metadata": {
                "root": str(root),
                "git_head": execution_root_before["head"],
                "working_tree_dirty": execution_root_before["dirty"],
                "source_repository_root": str(root),
                "source_git_head": source_before["head"],
                "source_worktree_dirty": source_before["dirty"],
                "harness_repository_root": str(REPOSITORY_ROOT),
                "harness_git_head": harness_before["head"],
                "harness_worktree_dirty": harness_before["dirty"],
                "working_tree_commands_sha256": source_before["commands_sha256"],
                "benchmark_script_sha256": source_before["benchmark_sha256"],
                "harness_identity_unchanged": True,
                "source_identity_unchanged": True,
                "execution_root_identity_unchanged": True,
                "config_fingerprint": config_fingerprint,
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "cpu": platform.processor() or platform.uname().processor,
                "logical_cpus": os.cpu_count(),
                "total_memory_bytes": _total_memory_bytes(),
                "git_version": git_version,
                "shell_path": shell_path,
                "shell_version": shell_version,
                "python": sys.version,
                "command": COMMAND,
                "light_samples_per_concurrency": light_samples,
                "paired_expensive_runs": paired_runs,
                "pair_order_seed": order_seed,
                "percentile_method": "nearest-rank",
            },
            "stages": {
                "classification": _summary(classification_samples),
                "fingerprint_force": _summary(forced_fingerprint_samples),
                "fingerprint_warm": _summary(warm_fingerprint_samples),
                "command_cache_miss": _summary(paired_miss_samples),
                "command_cache_hit": _summary(paired_hit_samples),
                "cache_hit_latency_reduction_pct": {
                    "n": len(pair_reductions),
                    "p50": round(_nearest_rank(pair_reductions, 50), 2),
                    "p95": round(_nearest_rank(pair_reductions, 95), 2),
                    "paired_raw": [round(value, 2) for value in pair_reductions],
                },
                "cache_pair_order": {
                    "orders": [list(order) for order in paired_cache["orders"]],
                    "order_strata": paired_cache["order_summary"],
                    "raw_pairs": paired_cache["pairs"],
                    "fixture": paired_cache["fixture"],
                    "accounting": paired_cache["cache_accounting"],
                },
                "structured_process_startup": _first_and_repeated(startup_samples),
                "shell_process_startup": _first_and_repeated(shell_startup_samples),
                "concurrent_warm_cache_hits": concurrency_results,
                "dual_stream_capture": {
                    "wall_ms": _summary([row["wall_ms"] for row in capture_records]),
                    "stdout_bytes": [row["stdout_bytes"] for row in capture_records],
                    "stderr_bytes": [row["stderr_bytes"] for row in capture_records],
                    "callback_chunks": [row["callback_chunks"] for row in capture_records],
                    "callback_stdout_bytes": [row["callback_stdout_bytes"] for row in capture_records],
                    "callback_stderr_bytes": [row["callback_stderr_bytes"] for row in capture_records],
                    "dropped_chunks": [row["dropped_chunks"] for row in capture_records],
                    "dispatch_incomplete": [row["dispatch_incomplete"] for row in capture_records],
                },
                "dual_stream_capture_without_callback": {
                    "wall_ms": _summary(
                        [row["wall_ms"] for row in capture_without_callback_records]
                    ),
                    "stdout_bytes": [row["stdout_bytes"] for row in capture_without_callback_records],
                    "stderr_bytes": [row["stderr_bytes"] for row in capture_without_callback_records],
                    "callback_enabled": False,
                },
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--light-samples", type=int, default=1000)
    parser.add_argument("--paired-runs", type=int, default=30)
    parser.add_argument("--pair-order-seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.light_samples <= 10_000:
        parser.error("--light-samples must be between 1 and 10000")
    if not 1 <= args.paired_runs <= 100:
        parser.error("--paired-runs must be between 1 and 100")
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    protected_roots = (REPOSITORY_ROOT.resolve(), root)
    if any(output.is_relative_to(protected) for protected in protected_roots):
        parser.error("--output must be outside source and benchmark repositories")
    if output.exists():
        parser.error("--output already exists; choose a new path to preserve prior evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = run_benchmark(
        root,
        args.light_samples,
        args.paired_runs,
        order_seed=args.pair_order_seed,
    )
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    except FileExistsError:
        parser.error("--output already exists; choose a new path to preserve prior evidence")
    print(json.dumps({"success": True, "output": str(output), "schema": SCHEMA}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
