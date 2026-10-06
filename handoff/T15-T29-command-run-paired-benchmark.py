#!/usr/bin/env python3
"""Paired, serial CommandBroker.run benchmark for T15/T29.

This is a driver, not an acceptance receipt. It refuses to run until both
source commits and commands.py hashes are supplied and verified. Do not start
it without T20's explicit serial benchmark slot.

Each source observation runs in a fresh Python worker. Workers run sequentially
in deterministic AB/BA order; no benchmark calls overlap. Temporary clones are
created from the pinned commits, so source worktrees remain untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


TASK_ID = "T29"
BLOCKS = 3
PAIRS_PER_BLOCK = 30
BOOTSTRAP_RESAMPLES = 10_000
DEFAULT_SEED = 7341
SCRATCH_NAME = ".t29-bench"
WORKLOADS = ("noop", "read4096", "write4096")
MODES = ("forced", "cache_hit")
PHASES = ("total_ms", "planning_ms", "execution_ms", "result_recovery_ms")
DRIVER_PATH = Path(__file__).resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires observations")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _median(values: list[float]) -> float:
    return _percentile(values, 0.5)


def _bootstrap_ci(values: list[float], seed: int) -> list[float]:
    rng = random.Random(seed)
    count = len(values)
    medians = [
        _median([values[rng.randrange(count)] for _ in range(count)])
        for _ in range(BOOTSTRAP_RESAMPLES)
    ]
    return [_percentile(medians, 0.025), _percentile(medians, 0.975)]


def _prepare_source(
    label: str,
    source_root: Path,
    commit: str,
    expected_commands_sha256: str,
    clone_root: Path,
) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    if not (source_root / ".git").exists():
        raise ValueError(f"{label} root is not a Git worktree: {source_root}")
    if not commit or _git(source_root, "rev-parse", f"{commit}^{{commit}}") != commit:
        raise ValueError(f"{label} commit must be a full, resolved commit ID")
    destination = clone_root / label
    clone = subprocess.run(
        ["git", "clone", "--shared", "--quiet", "--no-checkout", str(source_root), str(destination)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if clone.returncode:
        raise RuntimeError(f"{label} temporary clone failed: {clone.stderr.strip()[:500]}")
    _git(destination, "checkout", "--quiet", "--detach", commit)
    actual_commit = _git(destination, "rev-parse", "HEAD")
    if actual_commit != commit:
        raise ValueError(f"{label} checkout does not match pinned commit")
    commands_sha256 = _sha256_file(destination / "src/local_ai_hub/commands.py")
    if commands_sha256.lower() != expected_commands_sha256.lower():
        raise ValueError(f"{label} commands.py hash does not match supplied pin")
    harness = destination / "tests/test_command_performance_acceptance.py"
    return {
        "label": label,
        "root": destination,
        "source_root": source_root,
        "commit": actual_commit,
        "commands_sha256": commands_sha256,
        "harness_sha256": _sha256_file(harness),
    }


def _add_scratch_exclude(root: Path) -> None:
    exclude = root / ".git/info/exclude"
    current = exclude.read_text(encoding="utf-8", errors="replace") if exclude.exists() else ""
    marker = f"/{SCRATCH_NAME}/"
    if marker not in current.splitlines():
        with exclude.open("a", encoding="utf-8", newline="\n") as output:
            if current and not current.endswith(("\n", "\r")):
                output.write("\n")
            output.write(f"\n# T15/T29 disposable benchmark scratch\n{marker}\n")


def _workload_argv(name: str, scratch: Path) -> list[str]:
    if name == "noop":
        return [sys.executable, "-B", "-c", "pass"]
    if name == "read4096":
        return [
            sys.executable,
            "-B",
            "-c",
            "from pathlib import Path; import hashlib,sys; print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())",
            str(scratch / "read-4096.bin"),
        ]
    if name == "write4096":
        return [
            sys.executable,
            "-B",
            "-c",
            "from pathlib import Path; import hashlib,sys; p=Path(sys.argv[1]); p.write_bytes(b'x'*4096); print(hashlib.sha256(p.read_bytes()).hexdigest())",
            str(scratch / "write-4096.bin"),
        ]
    raise ValueError(f"unsupported workload: {name}")


def _worker(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve(strict=True)
    scratch = root / SCRATCH_NAME
    scratch.mkdir(parents=True, exist_ok=True)
    read_fixture = scratch / "read-4096.bin"
    read_fixture.write_bytes(bytes(range(256)) * 16)
    if _sha256_file(read_fixture) != "c8f5d0341d54d951a71b136e6e2afcb14d11ed8489a7ae126a8fee0df6ecf193":
        raise RuntimeError("read fixture hash mismatch")
    write_output = scratch / "write-4096.bin"

    sys.path.insert(0, str(root / "src"))
    sys.path.insert(0, str(root / "tests"))
    from local_ai_hub.commands import CommandInvocation  # type: ignore[import-not-found]
    from test_command_performance_acceptance import _command_broker  # type: ignore[import-not-found]

    with tempfile.TemporaryDirectory(prefix="t15-t29-state-") as state_directory:
        broker = _command_broker(Path(state_directory))
        invocation = CommandInvocation(argv=_workload_argv(args.workload, scratch), cwd=str(root), shell=False)
        if args.workload == "write4096":
            write_output.unlink(missing_ok=True)

        if args.mode == "cache_hit":
            prime = broker.run(invocation, str(root), "t29-bench", timeout=30, force=True)
            if not prime.get("success") or prime.get("cache_hit") is True:
                raise RuntimeError(f"cache priming failed: {prime.get('error', 'unexpected result')}")

        execution_spans: list[tuple[int, int]] = []
        execute = broker._execute

        def timed_execute(*call_args: Any, **call_kwargs: Any) -> dict[str, Any]:
            started = time.perf_counter_ns()
            try:
                return execute(*call_args, **call_kwargs)
            finally:
                execution_spans.append((started, time.perf_counter_ns()))

        broker._execute = timed_execute  # type: ignore[method-assign]
        started = time.perf_counter_ns()
        result = broker.run(
            invocation,
            str(root),
            "t29-bench",
            timeout=30,
            force=args.mode == "forced",
        )
        finished = time.perf_counter_ns()
        total_ms = (finished - started) / 1_000_000
        if len(execution_spans) > 1:
            raise RuntimeError("benchmark call executed more than one subprocess phase")
        if execution_spans:
            execute_start, execute_end = execution_spans[0]
            planning_ms = (execute_start - started) / 1_000_000
            execution_ms = (execute_end - execute_start) / 1_000_000
            result_recovery_ms = (finished - execute_end) / 1_000_000
            phase_partition = "bracketed"
        else:
            planning_ms = total_ms
            execution_ms = 0.0
            result_recovery_ms = 0.0
            phase_partition = "cache_or_preflight_no_execution"

        expected_cache_hit = args.mode == "cache_hit"
        if not result.get("success") or result.get("exit_code") != 0:
            raise RuntimeError(f"measured run failed: {result.get('error', result.get('exit_code'))}")
        if result.get("cache_hit") is not expected_cache_hit:
            raise RuntimeError(
                f"cache policy mismatch: expected {expected_cache_hit}, got {result.get('cache_hit')}"
            )
        scratch_file = read_fixture if args.workload == "read4096" else write_output
        scratch_digest = _sha256_file(scratch_file) if scratch_file.exists() else hashlib.sha256(b"").hexdigest()
        payload = {
            "success": bool(result.get("success")),
            "exit_code": int(result.get("exit_code", 0)),
            "stdout_sha256": hashlib.sha256(str(result.get("stdout", "")).encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(str(result.get("stderr", "")).encode("utf-8")).hexdigest(),
            "repository_revision": str(result.get("repository_revision", "")),
            "cache_hit": bool(result.get("cache_hit", False)),
            "scratch_sha256": scratch_digest,
            "total_ms": total_ms,
            "planning_ms": planning_ms,
            "execution_ms": execution_ms,
            "result_recovery_ms": result_recovery_ms,
            "phase_partition": phase_partition,
            "broker_phase_timings_ms": result.get("phase_timings_ms", {}),
        }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def _invoke_worker(source: dict[str, Any], workload: str, mode: str) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        str(DRIVER_PATH),
        "--worker",
        "--repo-root",
        str(source["root"]),
        "--workload",
        workload,
        "--mode",
        mode,
    ]
    completed = subprocess.run(
        command,
        cwd=str(source["root"]),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{source['label']} worker failed ({completed.returncode}): "
            f"{completed.stderr.strip()[-1000:]} {completed.stdout.strip()[-500:]}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source['label']} worker returned invalid JSON") from exc
    return result


def _build_summaries(observations: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    modes_by_workload = {"noop": MODES, "read4096": MODES, "write4096": ("forced",)}
    for workload, modes in modes_by_workload.items():
        for mode in modes:
            rows = [row for row in observations if row["workload"] == workload and row["mode"] == mode]
            for phase in PHASES:
                baseline = [float(row["baseline"][phase]) for row in rows]
                candidate = [float(row["candidate"][phase]) for row in rows]
                deltas = [right - left for left, right in zip(baseline, candidate)]
                faster_blocks = sum(
                    _median([float(row["candidate"][phase]) - float(row["baseline"][phase]) for row in rows if row["block"] == block]) < 0
                    for block in range(1, BLOCKS + 1)
                )
                summaries.append(
                    {
                        "workload": workload,
                        "mode": mode,
                        "phase": phase,
                        "n": len(rows),
                        "baseline_p50_ms": _median(baseline),
                        "baseline_p95_ms": _percentile(baseline, 0.95),
                        "candidate_p50_ms": _median(candidate),
                        "candidate_p95_ms": _percentile(candidate, 0.95),
                        "paired_median_delta_ms": _median(deltas),
                        "relative_delta_pct": 100 * _median(deltas) / _median(baseline) if _median(baseline) else 0.0,
                        "bootstrap_ci95_ms": _bootstrap_ci(deltas, seed + len(summaries)),
                        "faster_blocks": faster_blocks,
                    }
                )
    return summaries


def _run(args: argparse.Namespace) -> int:
    baseline_root = Path(args.baseline_root).resolve(strict=True)
    candidate_root = Path(args.candidate_root).resolve(strict=True)
    report_path = Path(args.report).expanduser().resolve()
    for source_root in (baseline_root, candidate_root):
        if report_path == source_root or source_root in report_path.parents:
            raise ValueError("report must be outside pinned source roots")
    if baseline_root == candidate_root:
        raise ValueError("baseline and candidate must be distinct source roots")

    with tempfile.TemporaryDirectory(prefix="t15-t29-paired-") as temporary:
        clone_root = Path(temporary)
        baseline = _prepare_source(
            "baseline", baseline_root, args.baseline_commit, args.baseline_commands_sha256, clone_root
        )
        candidate = _prepare_source(
            "candidate", candidate_root, args.candidate_commit, args.candidate_commands_sha256, clone_root
        )
        _add_scratch_exclude(baseline["root"])
        _add_scratch_exclude(candidate["root"])
        for source in (baseline, candidate):
            scratch = source["root"] / SCRATCH_NAME
            scratch.mkdir()
            fixture = scratch / "read-4096.bin"
            fixture.write_bytes(bytes(range(256)) * 16)
            if _sha256_file(fixture) != "c8f5d0341d54d951a71b136e6e2afcb14d11ed8489a7ae126a8fee0df6ecf193":
                raise RuntimeError("benchmark fixture does not match methodology pin")

        rng = random.Random(args.seed)
        observations: list[dict[str, Any]] = []
        modes_by_workload = {"noop": MODES, "read4096": MODES, "write4096": ("forced",)}
        pair_id = 0
        for workload, modes in modes_by_workload.items():
            for mode in modes:
                orders = ["AB", "BA"] * (BLOCKS * PAIRS_PER_BLOCK // 2)
                rng.shuffle(orders)
                cursor = 0
                for block in range(1, BLOCKS + 1):
                    for pair in range(1, PAIRS_PER_BLOCK + 1):
                        pair_id += 1
                        order = orders[cursor]
                        cursor += 1
                        versions = {"A": baseline, "B": candidate}
                        paired: dict[str, dict[str, Any]] = {}
                        for side in order:
                            source = versions[side]
                            if workload == "write4096":
                                (source["root"] / SCRATCH_NAME / "write-4096.bin").unlink(missing_ok=True)
                            paired[side] = _invoke_worker(source, workload, mode)
                        left, right = paired["A"], paired["B"]
                        observations.append(
                            {
                                "pair_id": pair_id,
                                "workload": workload,
                                "mode": mode,
                                "block": block,
                                "pair": pair,
                                "order": order,
                                "baseline": left,
                                "candidate": right,
                                "parity": {
                                    "success": left["success"] == right["success"],
                                    "exit_code": left["exit_code"] == right["exit_code"],
                                    "stdout": left["stdout_sha256"] == right["stdout_sha256"],
                                    "stderr": left["stderr_sha256"] == right["stderr_sha256"],
                                    "scratch_state": left["scratch_sha256"] == right["scratch_sha256"],
                                    "cache_policy": left["cache_hit"] == right["cache_hit"],
                                    "source_revision_recorded": bool(left["repository_revision"] and right["repository_revision"]),
                                },
                            }
                        )
                if workload != "write4096":
                    continue

        summaries = _build_summaries(observations, args.seed)
        correctness = all(all(row["parity"].values()) for row in observations)
        report = {
            "schema_version": 2,
            "task_id": TASK_ID,
            "method": "paired_command_broker_run_phased",
            "source": {
                "baseline": {key: baseline[key] for key in ("commit", "commands_sha256", "harness_sha256")},
                "candidate": {key: candidate[key] for key in ("commit", "commands_sha256", "harness_sha256")},
                "driver_sha256": _sha256_file(DRIVER_PATH),
            },
            "environment": {
                "os": platform.platform(),
                "python": platform.python_version(),
                "executable": str(Path(sys.executable).resolve()),
                "cpu": platform.processor() or platform.machine(),
                "seed": args.seed,
            },
            "parameters": {
                "blocks": BLOCKS,
                "pairs_per_block": PAIRS_PER_BLOCK,
                "pairs_per_workload_mode": BLOCKS * PAIRS_PER_BLOCK,
                "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
                "modes_by_workload": {name: list(modes) for name, modes in modes_by_workload.items()},
                "workloads": list(WORKLOADS),
                "concurrent_workers": 1,
                "phase_definition": {
                    "planning_ms": "run entry to first _execute entry; for cache hits, full run duration",
                    "execution_ms": "wall time inside _execute wrapper; zero when no execution occurs",
                    "result_recovery_ms": "last _execute return to run return; excludes rollback because workload succeeds",
                },
            },
            "observations": observations,
            "summaries": summaries,
            "decision": {
                "correctness_parity": correctness,
                "performance_win": None,
                "non_regression": None,
                "result": "inconclusive" if correctness else "fail",
                "reasons": [] if correctness else ["paired output/cache/scratch parity failed"],
                "interpretation": "Performance thresholds require independent review; this driver does not declare a win.",
            },
            "slot": {"t20_slot_id": args.t20_slot_id},
        }
        encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
        temporary_report.write_bytes(encoded)
        os.replace(temporary_report, report_path)
    print(json.dumps({"report": str(report_path), "pairs": len(observations), "sha256": _sha256_file(report_path)}, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root")
    parser.add_argument("--candidate-root")
    parser.add_argument("--baseline-commit")
    parser.add_argument("--candidate-commit")
    parser.add_argument("--baseline-commands-sha256")
    parser.add_argument("--candidate-commands-sha256")
    parser.add_argument("--t20-slot-id", help="explicit T20 serial-slot grant ID; required to prevent accidental runs")
    parser.add_argument("--report")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--repo-root", help=argparse.SUPPRESS)
    parser.add_argument("--workload", choices=WORKLOADS, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=MODES, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.worker:
        if not args.repo_root or not args.workload or not args.mode:
            raise SystemExit("worker requires repo root, workload, and mode")
        return _worker(args)
    required = (
        args.baseline_root,
        args.candidate_root,
        args.baseline_commit,
        args.candidate_commit,
        args.baseline_commands_sha256,
        args.candidate_commands_sha256,
        args.t20_slot_id,
        args.report,
    )
    if not all(required):
        raise SystemExit("runner requires T20 slot ID, pinned baseline/candidate roots/commits/commands.py hashes, and report path")
    return _run(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        raise SystemExit(f"benchmark aborted: {type(exc).__name__}: {exc}") from exc
