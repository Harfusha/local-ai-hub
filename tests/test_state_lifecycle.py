from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest
from local_ai_hub.state_lifecycle import (
    CURRENT_STATE_VERSION,
    STATE_VERSION_FILE,
    ensure_state_version,
    read_state_version,
    write_state_version,
)


def test_fresh_directory_initialization(tmp_path: Path):
    state_dir = tmp_path / "fresh_state"
    res = ensure_state_version(state_dir, target_version=6)

    assert res["status"] == "initialized"
    assert res["version"] == 6
    assert res["wiped"] is False
    assert (state_dir / STATE_VERSION_FILE).is_file()
    assert read_state_version(state_dir) == 6
    assert json.loads((state_dir / STATE_VERSION_FILE).read_text(encoding="utf-8"))["clean_slate_wiped"] is False


def test_existing_version_preserved_without_wiping(tmp_path: Path):
    state_dir = tmp_path / "v6_state"
    state_dir.mkdir(parents=True)
    write_state_version(state_dir, version=6)
    dummy_db = state_dir / "cache.sqlite"
    dummy_db.write_bytes(b"some cache")

    res = ensure_state_version(state_dir, target_version=6)
    assert res["status"] == "current"
    assert res["wiped"] is False
    assert dummy_db.exists()
    assert dummy_db.read_bytes() == b"some cache"


@pytest.mark.parametrize("stored_version", [None, 5, 7])
def test_version_mismatch_fails_closed_without_deleting_any_state(tmp_path: Path, stored_version: int | None):
    state_dir = tmp_path / "legacy_state"
    state_dir.mkdir(parents=True)
    durable_files = (
        "agent_state.sqlite",
        "workspace_memory.sqlite3",
        "artifacts.sqlite3",
        "evidence.sqlite3",
        "work_orders.sqlite3",
        "work_fencing.sqlite3",
    )
    before = {}
    for name in (*durable_files, "cache.sqlite", "unknown.sqlite"):
        path = state_dir / name
        before[name] = f"preserve:{name}".encode()
        path.write_bytes(before[name])
    diagnostic = state_dir / "diagnostics"
    diagnostic.mkdir()
    (diagnostic / "diag.json").write_text("preserve", encoding="utf-8")
    if stored_version is not None:
        write_state_version(state_dir, version=stored_version)
    marker_before = (state_dir / STATE_VERSION_FILE).read_bytes() if stored_version is not None else None

    with pytest.raises(RuntimeError, match="offline state conversion"):
        ensure_state_version(state_dir, target_version=6)

    assert {name: (state_dir / name).read_bytes() for name in before} == before
    assert (diagnostic / "diag.json").read_text(encoding="utf-8") == "preserve"
    if marker_before is None:
        assert not (state_dir / STATE_VERSION_FILE).exists()
    else:
        assert (state_dir / STATE_VERSION_FILE).read_bytes() == marker_before


def test_bootstrap_supervisor_files_allowed(tmp_path: Path):
    state_dir = tmp_path / "bootstrap_state"
    state_dir.mkdir(parents=True)
    # Simulate files created by supervisor before hub initializes state_version.json
    (state_dir / "supervisor.log").write_text("starting", encoding="utf-8")
    (state_dir / "supervisor.pid").write_text("12345", encoding="utf-8")
    (state_dir / "supervisor.lock").write_text("lock", encoding="utf-8")
    (state_dir / "supervisor.lock.guard").write_text("guard", encoding="utf-8")
    (state_dir / "supervisor.owner.json").write_text("{}", encoding="utf-8")
    (state_dir / "supervisor.status.json").write_text("{}", encoding="utf-8")
    logs_dir = state_dir / "logs"
    logs_dir.mkdir()
    (logs_dir / "hub_stderr.log").write_text("err", encoding="utf-8")

    res = ensure_state_version(state_dir, target_version=6)
    assert res["status"] == "initialized"
    assert res["version"] == 6
    assert (state_dir / STATE_VERSION_FILE).is_file()


def _initialize_state_version_in_process(state_dir: str, barrier, results) -> None:
    barrier.wait(timeout=10)
    results.put(ensure_state_version(state_dir, target_version=6)["status"])


def test_concurrent_first_start_initializes_state_once(tmp_path: Path):
    state_dir = tmp_path / "concurrent_state"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(target=_initialize_state_version_in_process, args=(str(state_dir), barrier, results))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
    try:
        assert all(process.exitcode == 0 for process in processes)
        assert sorted(results.get(timeout=2) for _ in processes) == ["current", "initialized"]
        assert read_state_version(state_dir) == 6
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
        results.close()

