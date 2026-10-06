"""Run the two historical T02 SQLite-warning selectors once with tracebacks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SELECTORS = (
    "tests/test_surface_benchmarks.py::test_run_benchmark_is_isolated_and_preserves_existing_scratch_data",
    "tests/test_surface_benchmarks.py::test_component_baselines_measure_graph_rag_batch_parent_seed_and_serena",
)
SOURCE_FILES = (
    "tests/test_surface_benchmarks.py",
    "tools/benchmark_surfaces.py",
    "src/local_ai_hub/async_jobs.py",
)
TIMEOUT_SECONDS = 120


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_hash(path: Path) -> str:
    return _sha256(path.read_bytes())


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _failed_nodes(output: bytes) -> list[str]:
    text = output.decode("utf-8", errors="replace")
    return list(dict.fromkeys(re.findall(r"(?m)^(?:FAILED|ERROR)\s+(\S+)", text)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, required=True,
        help="new directory outside repository for receipt and raw logs",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = args.out_dir.expanduser().resolve()
    if out_dir.is_relative_to(repo_root):
        parser.error("receipt directory must be outside the repository")
    if out_dir.exists():
        parser.error("receipt directory must be new; existing evidence is never overwritten")
    for relative in SOURCE_FILES:
        if not (repo_root / relative).is_file():
            parser.error(f"required source file is missing: {relative}")

    out_dir.mkdir(parents=True, exist_ok=False)
    state_root = out_dir / "pytest-state-root"
    command = [
        sys.executable,
        "-X", "tracemalloc=5",
        "-W", "error::ResourceWarning",
        "-m", "pytest",
        "-v", "--tb=long", "-s",
        "-p", "no:cacheprovider",
        f"--basetemp={state_root}",
        *SELECTORS,
    ]
    child_env = os.environ.copy()
    trace_was_set = "T02_TRACE" in child_env
    child_env.pop("T02_TRACE", None)
    child_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    child_env["PYTHONUNBUFFERED"] = "1"

    started = datetime.now(timezone.utc).isoformat()
    start = time.perf_counter()
    status = "failed"
    exit_code = 1
    stdout_path = out_dir / "pytest.stdout.log"
    stderr_path = out_dir / "pytest.stderr.log"
    try:
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=repo_root,
                env=child_env,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            try:
                exit_code = process.wait(timeout=TIMEOUT_SECONDS)
                status = "passed" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                exit_code, status = 124, "timeout"
    except OSError as exc:
        stderr_path.write_text(str(exc), encoding="utf-8")
        exit_code, status = 127, "spawn_error"

    stdout = stdout_path.read_bytes()
    stderr = stderr_path.read_bytes()
    combined = stdout + b"\n" + stderr
    receipt: dict[str, Any] = {
        "schema_version": "t02-sqlite-warning-diagnostic/v1",
        "created_utc": started,
        "repo_root": str(repo_root),
        "head": _git(repo_root, "rev-parse", "HEAD"),
        "python_version": sys.version.split()[0],
        "selectors": list(SELECTORS),
        "selector_run_count": 1,
        "timeout_seconds": TIMEOUT_SECONDS,
        "command": command,
        "state_root": str(state_root),
        "environment_policy": {
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONUNBUFFERED": "1",
            "pytest_capture": "disabled; raw streams saved separately",
            "T02_TRACE_removed": trace_was_set,
        },
        "source_sha256": {
            **{name: _file_hash(repo_root / name) for name in SOURCE_FILES},
            Path(__file__).resolve().relative_to(repo_root).as_posix(): _file_hash(Path(__file__)),
        },
        "status": status,
        "exit_code": exit_code,
        "duration_seconds": round(time.perf_counter() - start, 3),
        "resource_warning_mentions": combined.count(b"ResourceWarning"),
        "failed_node_ids": _failed_nodes(combined),
        "stdout_file": stdout_path.name,
        "stdout_sha256": _sha256(stdout),
        "stderr_file": stderr_path.name,
        "stderr_sha256": _sha256(stderr),
    }
    (out_dir / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(json.dumps({"receipt": str(out_dir / "receipt.json"), "status": status,
                      "exit_code": exit_code, "resource_warning_mentions": receipt["resource_warning_mentions"]}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
