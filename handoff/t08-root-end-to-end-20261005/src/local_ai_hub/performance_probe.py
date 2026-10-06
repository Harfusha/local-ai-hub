from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from typing import Sequence


SUPPORTED_STAGES = frozenset({"preprocess", "index", "rag", "mcp", "http"})


def validate_stage(stage: str) -> str:
    value = str(stage).strip().lower()
    if value not in SUPPORTED_STAGES:
        raise ValueError(f"unknown performance stage: {stage}")
    return value


def percentile(samples: Sequence[float], percentage: float) -> float:
    if not samples:
        raise ValueError("percentile requires at least one sample")
    if not 0 <= percentage <= 100:
        raise ValueError("percentage must be between 0 and 100")
    ordered = sorted(float(sample) for sample in samples)
    position = (len(ordered) - 1) * (percentage / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def build_profiler_command(profiler: str, command: Sequence[str]) -> list[str]:
    if not command:
        raise ValueError("a target command is required")
    name = str(profiler).strip().lower()
    target = list(command)
    if name == "py-spy":
        return ["py-spy", "record", "--subprocesses", "--output", "performance.svg", "--", *target]
    if name == "scalene":
        return ["scalene", "--cpu", "--memory", "--", *target]
    raise ValueError(f"unsupported profiler: {profiler}")


def profiler_status(profiler: str) -> dict[str, object]:
    command = str(profiler).strip().lower()
    return {"name": command, "available": bool(shutil.which(command))}


def run_probe(
    stage: str,
    command: Sequence[str],
    *,
    iterations: int = 3,
    warmup: int = 1,
    timeout_seconds: float = 300.0,
) -> dict[str, object]:
    stage = validate_stage(stage)
    if not command:
        raise ValueError("a target command is required")
    iterations = max(1, min(int(iterations), 100))
    warmup = max(0, min(int(warmup), 20))
    timeout_seconds = max(0.1, min(float(timeout_seconds), 3600.0))

    for _ in range(warmup):
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False)
        if result.returncode:
            raise RuntimeError(f"warmup command failed with exit code {result.returncode}")

    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if result.returncode:
            raise RuntimeError(f"performance command failed with exit code {result.returncode}")
        samples.append(elapsed_ms)

    return {
        "success": True,
        "stage": stage,
        "iterations": iterations,
        "warmup": warmup,
        "command": list(command),
        "throughput_per_second": round(iterations / (sum(samples) / 1000.0), 4),
        "wall_ms": {
            "min": round(min(samples), 3),
            "mean": round(sum(samples) / len(samples), 3),
            "p50": round(percentile(samples, 50), 3),
            "p95": round(percentile(samples, 95), 3),
            "p99": round(percentile(samples, 99), 3),
            "max": round(max(samples), 3),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded Local AI Hub performance probe")
    parser.add_argument("--stage", required=True, choices=sorted(SUPPORTED_STAGES))
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--profiler", choices=("py-spy", "scalene"))
    parser.add_argument("command", nargs=argparse.REMAINDER, help="target command after --")
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    report = run_probe(args.stage, command, iterations=args.iterations, warmup=args.warmup, timeout_seconds=args.timeout)
    if args.profiler:
        report["profiler"] = profiler_status(args.profiler)
        report["profiler_command"] = build_profiler_command(args.profiler, command)
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
