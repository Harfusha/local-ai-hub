"""Repeat the T02 pytest suite and preserve bounded, hash-addressed receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TESTS = ("tests/test_benchmark_suite.py", "tests/test_surface_benchmarks.py")
TRACKED_INPUTS = (
    "tools/benchmark_surfaces.py",
    "tests/test_benchmark_suite.py",
    "tests/test_surface_benchmarks.py",
    "src/local_ai_hub/async_jobs.py",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def run_attempt(
    command: list[str], *, repo_root: Path, out_dir: Path, label: str, timeout_seconds: float,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    started = time.perf_counter()
    exit_code: int
    status: str
    try:
        result = subprocess.run(
            command, cwd=repo_root, capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
        stdout, stderr, exit_code = _text(result.stdout), _text(result.stderr), result.returncode
        status = "passed" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        stdout = _text(exc.stdout if exc.stdout is not None else exc.output)
        stderr, exit_code, status = _text(exc.stderr), 124, "timeout"
    except OSError as exc:
        stdout, stderr, exit_code, status = "", str(exc), 127, "spawn_error"
    finished_at = _utc_now()

    stdout_file, stderr_file = f"{label}.stdout.log", f"{label}.stderr.log"
    (out_dir / stdout_file).write_text(stdout, encoding="utf-8")
    (out_dir / stderr_file).write_text(stderr, encoding="utf-8")
    combined = stdout + ("\n" if stdout and stderr else "") + stderr
    return {
        "label": label,
        "status": status,
        "exit_code": exit_code,
        "started_utc": started_at,
        "finished_utc": finished_at,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "timeout_seconds": timeout_seconds,
        "command": command,
        "stdout_file": stdout_file,
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "stderr_file": stderr_file,
        "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        "failed_node_ids": list(dict.fromkeys(re.findall(r"(?m)^(?:FAILED|ERROR)\s+(\S+)", combined))),
        "last_output_line": next((line for line in reversed(combined.splitlines()) if line.strip()), ""),
    }


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True, help="new directory outside the repository")
    parser.add_argument("--python", default=sys.executable, help="Python executable for pytest")
    parser.add_argument("--attempts", type=int, default=25)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--tests", nargs="+", default=list(DEFAULT_TESTS))
    parser.add_argument("--reverse-control", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = args.out_dir.expanduser().resolve()
    if not 1 <= args.attempts <= 100 or not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("attempts must be 1..100 and timeout must be finite and positive")
    if out_dir.is_relative_to(repo_root):
        parser.error("receipt directory must be outside the repository")
    if out_dir.exists():
        parser.error("receipt directory must be new; existing evidence is never overwritten")
    test_paths = [Path(name) for name in args.tests]
    if any(not (repo_root / name).resolve().is_relative_to(repo_root) for name in test_paths):
        parser.error("test paths must remain inside the repository")
    if any(not (repo_root / name).is_file() for name in test_paths):
        parser.error("every test path must exist")
    out_dir.mkdir(parents=True, exist_ok=False)

    def pytest_command(paths: list[Path]) -> list[str]:
        return [args.python, "-m", "pytest", "-q", "--tb=short", *[p.as_posix() for p in paths]]

    command = pytest_command(test_paths)
    attempts = [
        run_attempt(command, repo_root=repo_root, out_dir=out_dir, label=f"ordered-{i:02d}",
                    timeout_seconds=args.timeout_seconds)
        for i in range(1, args.attempts + 1)
    ]
    reverse = None
    if args.reverse_control:
        reverse = run_attempt(
            pytest_command(list(reversed(test_paths))), repo_root=repo_root, out_dir=out_dir,
            label="reverse-control", timeout_seconds=args.timeout_seconds,
        )

    input_paths = list(dict.fromkeys((*TRACKED_INPUTS, Path(__file__).resolve().relative_to(repo_root).as_posix(), *args.tests)))
    status = _git(repo_root, "status", "--porcelain", "--untracked-files=all")
    all_runs = [*attempts, *([reverse] if reverse else [])]
    receipt = {
        "schema_version": "t02-pytest-repeat/v1",
        "schema_file": "tools/schemas/t02-pytest-repeat-v1.schema.json",
        "started_utc": attempts[0]["started_utc"],
        "finished_utc": _utc_now(),
        "repo_root": str(repo_root),
        "head": _git(repo_root, "rev-parse", "HEAD"),
        "branch": _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "working_tree_dirty": bool(status),
        "dirty_paths": [line[3:] for line in status.splitlines() if len(line) > 3],
        "inputs_sha256": {
            name: _sha256((repo_root / name).resolve()) for name in input_paths
        },
        "attempts_target": args.attempts,
        "command": command,
        "attempts": attempts,
        "reverse_control": reverse,
        "success": all(run["status"] == "passed" for run in all_runs),
    }
    temporary = out_dir / ".receipt.json.tmp"
    receipt_path = out_dir / "receipt.json"
    temporary.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(receipt_path)
    print(json.dumps({"receipt_path": str(receipt_path), "success": receipt["success"]}, separators=(",", ":")))
    return 0 if receipt["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
