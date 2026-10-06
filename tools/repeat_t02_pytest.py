"""Repeat one allowlisted T02 regression selector with external evidence receipts.

This helper performs no benchmark or inference. Keep invocations candidate-only,
serial, bounded, and explicitly authorized by the active T20 test slot.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_TARGET_SELECTOR = (
    "tests/test_async_jobs.py::"
    "test_early_delayed_dispatch_callback_preserves_queued_cancellation"
)
_ALLOWED_SELECTORS = frozenset({_TARGET_SELECTOR})
_INPUT_PATHS = (
    "src/local_ai_hub/async_jobs.py",
    "tests/test_async_jobs.py",
)
_MAX_REPEATS = 50
_MAX_TIME_BUDGET_SECONDS = 900


def _validate_repeat_count(value: int) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_REPEATS:
        raise ValueError(f"repeat count must be between 1 and {_MAX_REPEATS}")
    return value


def _resolve_external_output(output_dir: Path, repository_root: Path) -> Path:
    resolved = output_dir.expanduser().resolve()
    repository = repository_root.resolve()
    if resolved == repository or repository in resolved.parents:
        raise ValueError("output directory must be outside the repository")
    return resolved


def _command_for_attempt(python: str, selector: str, basetemp: Path) -> list[str]:
    if selector not in _ALLOWED_SELECTORS:
        raise ValueError(f"unsupported T02 selector: {selector}")
    return [
        python, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "--tb=short", "--basetemp", str(basetemp), selector,
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input_hashes(repository_root: Path) -> dict[str, str]:
    return {
        relative: _sha256(repository_root / relative)
        for relative in _INPUT_PATHS
    }


def _git_revision(repository_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _decode_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def run_repetitions(
    *,
    selector: str,
    repeat_count: int,
    output_dir: Path,
    time_budget_seconds: int = 900,
    repository_root: Path = _REPOSITORY_ROOT,
) -> int:
    repeat_count = _validate_repeat_count(repeat_count)
    if type(time_budget_seconds) is not int or not 1 <= time_budget_seconds <= _MAX_TIME_BUDGET_SECONDS:
        raise ValueError(f"time budget must be between 1 and {_MAX_TIME_BUDGET_SECONDS} seconds")
    if selector not in _ALLOWED_SELECTORS:
        raise ValueError(f"unsupported T02 selector: {selector}")

    repository = repository_root.resolve()
    evidence_dir = _resolve_external_output(output_dir, repository)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    logs_dir = evidence_dir / "logs"
    logs_dir.mkdir()
    receipt_path = evidence_dir / "receipt.json"
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress",
        "repository_root": str(repository),
        "revision": _git_revision(repository),
        "selector": selector,
        "repeat_count_requested": repeat_count,
        "time_budget_seconds": time_budget_seconds,
        "inputs_before": _input_hashes(repository),
        "attempts": [],
    }
    _write_receipt(receipt_path, receipt)
    deadline = time.monotonic() + time_budget_seconds
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    try:
        for attempt_number in range(1, repeat_count + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            basetemp = evidence_dir / f"pytest-tmp-{attempt_number:03d}"
            command = _command_for_attempt(sys.executable, selector, basetemp)
            started_at = datetime.now(timezone.utc).isoformat()
            started = time.monotonic()
            outcome = "timeout"
            return_code: int | None = None
            try:
                completed = subprocess.run(
                    command,
                    cwd=repository,
                    env=environment,
                    capture_output=True,
                    check=False,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=remaining,
                )
                return_code = completed.returncode
                outcome = "passed" if return_code == 0 else "failed"
                output = f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            except subprocess.TimeoutExpired as exc:
                output = (
                    f"stdout:\n{_decode_output(exc.stdout)}\n"
                    f"stderr:\n{_decode_output(exc.stderr)}"
                )
            duration = round(time.monotonic() - started, 3)
            log_path = logs_dir / f"attempt-{attempt_number:03d}.log"
            log_path.write_text(
                f"command: {json.dumps(command)}\n"
                f"outcome: {outcome}\nreturn_code: {return_code}\n{output}",
                encoding="utf-8",
            )
            receipt["attempts"].append({
                "number": attempt_number,
                "started_at": started_at,
                "duration_seconds": duration,
                "outcome": outcome,
                "return_code": return_code,
                "log": str(log_path),
                "log_sha256": _sha256(log_path),
            })
            _write_receipt(receipt_path, receipt)
            if outcome == "timeout":
                break
    except KeyboardInterrupt:
        receipt["status"] = "interrupted"
        receipt["inputs_after"] = _input_hashes(repository)
        _write_receipt(receipt_path, receipt)
        return 130

    receipt["inputs_after"] = _input_hashes(repository)
    attempts = receipt["attempts"]
    receipt["status"] = (
        "complete"
        if len(attempts) == repeat_count and all(item["outcome"] == "passed" for item in attempts)
        else "failed"
        if any(item["outcome"] == "failed" for item in attempts)
        else "incomplete"
    )
    _write_receipt(receipt_path, receipt)
    print(json.dumps({
        "status": receipt["status"],
        "attempts": len(attempts),
        "passed": sum(item["outcome"] == "passed" for item in attempts),
        "receipt": str(receipt_path),
    }, ensure_ascii=False))
    return 0 if receipt["status"] == "complete" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selector", choices=sorted(_ALLOWED_SELECTORS), default=_TARGET_SELECTOR)
    parser.add_argument("--repeat", type=int, default=25)
    parser.add_argument("--output-dir", type=Path, required=True, help="new evidence directory outside the repository")
    parser.add_argument("--time-budget-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        return run_repetitions(
            selector=args.selector,
            repeat_count=args.repeat,
            output_dir=args.output_dir,
            time_budget_seconds=args.time_budget_seconds,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
