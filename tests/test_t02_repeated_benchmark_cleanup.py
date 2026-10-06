from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

import tools.benchmark_surfaces as surface_benchmarks
from local_ai_hub.async_jobs import AsyncJobManager


def test_minimal_baseline_comparison_cancels_and_closes_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch_root = tmp_path / "scratch"
    state_root = tmp_path / "state"
    close_receipts: list[dict[str, Any]] = []
    original_close = AsyncJobManager.close

    def inspect_close(manager: AsyncJobManager) -> None:
        original_close(manager)
        path = Path(manager.path)
        if not path.resolve().is_relative_to(scratch_root.resolve()):
            return

        handles = tuple(manager._workers) + tuple(manager._dispatchers) + tuple(manager._delayed_dispatch.values())
        live_threads = [thread.name for thread in handles if thread.is_alive()]
        live_processes = [
            str(process.pid)
            for processes in manager._processes.values()
            for process in processes
            if hasattr(process, "poll") and process.poll() is None
        ]
        states: dict[str, int] = {}
        lock_acquired = False
        if path.is_file():
            connection = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=0.1)
            try:
                connection.execute("BEGIN IMMEDIATE")
                lock_acquired = True
                states = {
                    str(state): int(count)
                    for state, count in connection.execute(
                        "SELECT state,COUNT(*) FROM async_jobs GROUP BY state"
                    )
                }
                connection.rollback()
            finally:
                connection.close()
        close_receipts.append({
            "database_exists_after_close": path.is_file(),
            "shutdown": manager._shutdown.is_set(),
            "live_threads": live_threads,
            "live_processes": live_processes,
            "sqlite_write_lock_acquired": lock_acquired,
            "job_states": states,
        })

    monkeypatch.setattr(AsyncJobManager, "close", inspect_close)
    run = surface_benchmarks.run_benchmark
    arguments = {
        "state_dir": state_root,
        "scratch_dir": scratch_root,
        "file_count": 1,
        "rag_chunks": 1,
        "repetitions": 1,
        "light_repetitions": 1,
        "comparison_repetitions": 1,
        "concurrency": (1,),
    }

    baseline = run(**arguments)
    assert baseline["success"] is True
    compared = run(**arguments, baseline_record=baseline)
    assert compared["success"] is True
    comparison = compared.get("comparison")
    assert isinstance(comparison, dict), json.dumps(close_receipts, sort_keys=True)
    persisted = json.loads(Path(compared["record_path"]).read_text(encoding="utf-8"))
    assert persisted["comparison"] == comparison
    print("T02_CANCEL_CLEANUP=" + json.dumps(close_receipts, sort_keys=True))

    assert len(close_receipts) == 2, json.dumps(close_receipts, sort_keys=True)
    for receipt in close_receipts:
        assert receipt["shutdown"] is True, json.dumps(close_receipts, sort_keys=True)
        assert receipt["live_threads"] == [], json.dumps(close_receipts, sort_keys=True)
        assert receipt["live_processes"] == [], json.dumps(close_receipts, sort_keys=True)
        assert receipt["sqlite_write_lock_acquired"] is True, json.dumps(close_receipts, sort_keys=True)
        assert not ({"queued", "running"} & set(receipt["job_states"])), json.dumps(close_receipts, sort_keys=True)
    assert list(scratch_root.iterdir()) == []
