from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from collections.abc import Mapping
import math
from typing import Any, Sequence

from .process_utils import hidden_run_kwargs


SUPPORTED_STAGES = frozenset({"preprocess", "index", "rag", "mcp", "http"})


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def is_valid_stage(stage: object) -> bool:
    if isinstance(stage, bool) or not isinstance(stage, str):
        return False
    return stage.replace("\x00", "").strip().lower() in SUPPORTED_STAGES


def validate_stage(stage: str) -> str:
    if isinstance(stage, bool) or not isinstance(stage, str):
        raise ValueError(f"unknown performance stage: {stage}")
    value = stage.replace("\x00", "").strip().lower()
    if value not in SUPPORTED_STAGES:
        raise ValueError(f"unknown performance stage: {stage}")
    return value


def percentile(samples: Sequence[float], percentage: float) -> float:
    if isinstance(percentage, bool) or not isinstance(percentage, (int, float)):
        raise ValueError("percentage must be a finite number between 0 and 100")
    p = float(percentage)
    if not math.isfinite(p) or not 0 <= p <= 100:
        raise ValueError("percentage must be between 0 and 100")
    if not samples:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(
        val for s in samples if not isinstance(s, bool) and (val := _safe_float(s)) is not None
    )
    if not ordered:
        raise ValueError("percentile requires at least one valid sample")
    position = (len(ordered) - 1) * (p / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def format_probe_summary(report: Mapping[str, Any] | object) -> str:
    if not isinstance(report, Mapping):
        return ""
    stage = str(report.get("stage") or "unknown")
    wall = report.get("wall_ms") if isinstance(report.get("wall_ms"), Mapping) else {}
    p95 = wall.get("p95", 0.0)
    throughput = report.get("throughput_per_second", 0.0)
    return f"stage={stage} p95={p95}ms throughput={throughput}/s"


def build_profiler_command(profiler: str, command: Sequence[str]) -> list[str]:
    if not command:
        raise ValueError("a target command is required")
    name = str(profiler).replace("\x00", "").strip().lower()
    target = list(command)
    if name == "py-spy":
        return ["py-spy", "record", "--subprocesses", "--output", "performance.svg", "--", *target]
    if name == "scalene":
        return ["scalene", "--cpu", "--memory", "--", *target]
    raise ValueError(f"unsupported profiler: {profiler}")


def profiler_status(profiler: str) -> dict[str, object]:
    command = str(profiler).replace("\x00", "").strip().lower()
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
    safe_iter = 3 if isinstance(iterations, bool) else max(1, min(int(_safe_float(iterations) or 3), 100))
    safe_warmup = 1 if isinstance(warmup, bool) else max(0, min(int(_safe_float(warmup) or 1), 20))
    safe_timeout = (
        300.0
        if isinstance(timeout_seconds, bool)
        else max(0.1, min(float(_safe_float(timeout_seconds) or 300.0), 3600.0))
    )

    for _ in range(safe_warmup):
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=safe_timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if result.returncode:
            raise RuntimeError(f"warmup command failed with exit code {result.returncode}")

    samples: list[float] = []
    for _ in range(safe_iter):
        started = time.perf_counter()
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=safe_timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if result.returncode:
            raise RuntimeError(f"performance command failed with exit code {result.returncode}")
        samples.append(elapsed_ms)

    return {
        "success": True,
        "stage": stage,
        "iterations": safe_iter,
        "warmup": safe_warmup,
        "command": list(command),
        "throughput_per_second": round(safe_iter / (sum(samples) / 1000.0), 4),
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
