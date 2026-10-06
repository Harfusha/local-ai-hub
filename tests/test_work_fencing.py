from __future__ import annotations

import multiprocessing
import json
import os
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from queue import Empty

import pytest

from local_ai_hub.work_fencing import (
    FencingLeaseStore,
    LeaseLostError,
    LeaseUnavailableError,
    normalize_paths,
)


def _claim_overlapping_path(db_path: str, root: str, owner: str, start, results) -> None:
    store = FencingLeaseStore(Path(db_path))
    start.wait(timeout=10)
    try:
        attempt = store.claim_attempt(root, f"work-{owner}", owner, ttl_seconds=30)
        lease = store.acquire(
            root, owner, ["src/shared.py"], ttl_seconds=30, attempt=attempt
        )
    except LeaseUnavailableError:
        results.put((owner, "busy", 0))
    else:
        results.put((owner, "acquired", lease.fencing_token))


def _record_race_order(order, lock) -> int:
    with lock:
        order.value += 1
        return int(order.value)


def _guarded_race_writer(db_path: str, root_s: str, started, release, order, lock, results) -> None:
    root = Path(root_s)
    try:
        store = FencingLeaseStore(Path(db_path), clock=lambda: 100.0)
        attempt = store.claim_attempt(root, "work-commit-race", "writer", ttl_seconds=5)
        lease = store.acquire(root, "writer", ["artifact.txt"], ttl_seconds=5, attempt=attempt)
        with store.commit_guard(lease, ["artifact.txt"]):
            (root / "artifact.txt").write_text("writer\n", encoding="utf-8")
            started.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test did not release guarded writer")
        writer_order = _record_race_order(order, lock)
        results.put(("writer", "committed", attempt.fencing_token, lease.fencing_token, writer_order))
    except BaseException as exc:
        started.set()
        results.put(("writer", "failed", type(exc).__name__, str(exc)))


def _claim_successor_during_guard(
    db_path: str, root_s: str, attempting, claimed, order, lock, results
) -> None:
    root = Path(root_s)
    attempting.set()
    try:
        store = FencingLeaseStore(Path(db_path), clock=lambda: 106.0)
        attempt = store.claim_attempt(root, "work-commit-race", "successor", ttl_seconds=30)
        claimed.set()
        successor_order = _record_race_order(order, lock)
        lease = store.acquire(root, "successor", ["artifact.txt"], ttl_seconds=30, attempt=attempt)
        with store.commit_guard(lease, ["artifact.txt"]):
            (root / "artifact.txt").write_text("successor\n", encoding="utf-8")
        results.put(("successor", "claimed", attempt.fencing_token, lease.fencing_token, successor_order))
    except BaseException as exc:
        attempting.set()
        results.put(("successor", "failed", type(exc).__name__, str(exc)))


def test_cross_process_contenders_get_one_overlapping_writer(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    db_path = tmp_path / "fences.sqlite3"
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_claim_overlapping_path,
            args=(str(db_path), str(root), f"owner-{index}", start, results),
        )
        for index in range(2)
    ]
    for worker in workers:
        worker.start()
    start.set()
    try:
        outcomes = [results.get(timeout=15) for _ in workers]
    except Empty:
        pytest.fail("lease contenders did not report a result")
    finally:
        for worker in workers:
            worker.join(timeout=15)
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)

    assert all(worker.exitcode == 0 for worker in workers)
    assert sorted(result[1] for result in outcomes) == ["acquired", "busy"]
    assert len({result[2] for result in outcomes if result[1] == "acquired"}) == 1


def test_cross_process_successor_cannot_supersede_writer_inside_commit_guard(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    db_path = tmp_path / "fences.sqlite3"
    context = multiprocessing.get_context("spawn")
    writer_started = context.Event()
    release_writer = context.Event()
    successor_attempting = context.Event()
    successor_claimed = context.Event()
    order = context.Value("i", 0)
    order_lock = context.Lock()
    results = context.Queue()
    writer = context.Process(
        target=_guarded_race_writer,
        args=(str(db_path), str(root), writer_started, release_writer, order, order_lock, results),
    )
    successor = context.Process(
        target=_claim_successor_during_guard,
        args=(str(db_path), str(root), successor_attempting, successor_claimed, order, order_lock, results),
    )
    writer.start()
    try:
        assert writer_started.wait(timeout=10), "writer did not enter its fenced write"
        successor.start()
        assert successor_attempting.wait(timeout=10), "successor did not reach claim_attempt"
        assert not successor_claimed.wait(timeout=0.5), "successor replaced writer before guarded commit"
    finally:
        release_writer.set()
        writer.join(timeout=12)
        if successor.pid is not None:
            successor.join(timeout=12)
        for process in (writer, successor):
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert writer.exitcode == 0
    assert successor.exitcode == 0
    outcomes = []
    try:
        outcomes = [results.get(timeout=3) for _ in range(2)]
    except Empty:
        pytest.fail(f"cross-process commit race did not report both results: {outcomes!r}")
    by_owner = {result[0]: result for result in outcomes}
    assert by_owner["writer"][1] == "committed", by_owner["writer"]
    assert by_owner["successor"][1] == "claimed", by_owner["successor"]
    writer_result = by_owner["writer"]
    successor_result = by_owner["successor"]
    assert successor_result[2] > writer_result[2]
    assert successor_result[3] > writer_result[3]
    assert writer_result[4] < successor_result[4]
    assert (root / "artifact.txt").read_text(encoding="utf-8") == "successor\n"


def test_disjoint_paths_can_coexist_but_overlapping_paths_cannot(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    store = FencingLeaseStore(tmp_path / "fences.sqlite3")
    first_attempt = store.claim_attempt(str(root), "work-a", "owner-a", ttl_seconds=60)
    disjoint_attempt = store.claim_attempt(str(root), "work-b", "owner-b", ttl_seconds=60)
    overlap_attempt = store.claim_attempt(str(root), "work-c", "owner-c", ttl_seconds=60)

    first = store.acquire(
        str(root), "owner-a", ["src/a.py"], ttl_seconds=60, attempt=first_attempt
    )
    disjoint = store.acquire(
        str(root), "owner-b", ["src/b.py"], ttl_seconds=60, attempt=disjoint_attempt
    )
    try:
        with pytest.raises(LeaseUnavailableError):
            store.acquire(
                str(root), "owner-c", ["src/a.py/child"], ttl_seconds=60,
                attempt=overlap_attempt,
            )
        assert first.fencing_token != disjoint.fencing_token
    finally:
        store.release(first)
        store.release(disjoint)
        store.release_attempt(first_attempt)
        store.release_attempt(disjoint_attempt)
        store.release_attempt(overlap_attempt)


def test_namespace_writer_token_starts_above_legacy_physical_token(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    store = FencingLeaseStore(tmp_path / "fences.sqlite3")
    legacy_scope = os.path.normcase(str(root.resolve()))
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO writer_fence_leases(lease_id,resource,owner_id,fencing_token,expires_at,paths_json,attempt_id,attempt_token,scope_id,active) "
            "VALUES(?,?,?,?,?,?,?,?,?,0)",
            ("legacy-lease", legacy_scope, "old-owner", 8, 0, '["src/shared.py"]', "", 0, legacy_scope),
        )
    coordination_id = "tenant-new"
    attempt = store.claim_attempt(
        root, "work-new", "owner-new", ttl_seconds=30,
        coordination_id=coordination_id,
    )

    lease = store.acquire(
        root, "owner-new", ["src/shared.py"], ttl_seconds=30,
        attempt=attempt, coordination_id=coordination_id,
    )

    assert lease.fencing_token > 8


@pytest.mark.skipif(os.name != "nt", reason="Windows paths are case-insensitive")
def test_case_aliases_cannot_claim_same_windows_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    store = FencingLeaseStore(tmp_path / "fences.sqlite3")

    first_attempt = store.claim_attempt(str(root), "work-a", "owner-a", ttl_seconds=60)
    second_attempt = store.claim_attempt(str(root), "work-b", "owner-b", ttl_seconds=60)
    first = store.acquire(
        str(root), "owner-a", ["Src/A.py"], ttl_seconds=60, attempt=first_attempt
    )
    try:
        with pytest.raises(LeaseUnavailableError):
            store.acquire(
                str(root), "owner-b", ["src/a.PY"], ttl_seconds=60,
                attempt=second_attempt,
            )
        with store.commit_guard(first, ["SRC/a.py"]):
            pass
    finally:
        store.release(first)
        store.release_attempt(first_attempt)
        store.release_attempt(second_attempt)


def test_commit_guard_rejects_expired_parent_attempt(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    now = [100.0]
    store = FencingLeaseStore(tmp_path / "fences.sqlite3", clock=lambda: now[0])
    attempt = store.claim_attempt(str(root), "work-a", "owner-a", ttl_seconds=5)
    lease = store.acquire(
        str(root), "owner-a", ["file.py"], ttl_seconds=30, attempt=attempt
    )
    now[0] = 106.0

    with pytest.raises(LeaseLostError, match="attempt"):
        with store.commit_guard(lease, ["file.py"]):
            pytest.fail("expired attempt entered the writer commit guard")


@pytest.mark.parametrize(("attempt_ttl", "lease_ttl"), ((5, 30), (30, 5)))
def test_commit_guard_revalidates_path_and_attempt_tokens_before_commit(
    tmp_path: Path, attempt_ttl: int, lease_ttl: int
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    now = [100.0]
    store = FencingLeaseStore(tmp_path / "fences.sqlite3", clock=lambda: now[0])
    attempt = store.claim_attempt(
        str(root), "work-commit-expiry", "writer", ttl_seconds=attempt_ttl
    )
    lease = store.acquire(
        str(root), "writer", ["artifact.txt"], ttl_seconds=lease_ttl, attempt=attempt
    )
    artifact = root / "artifact.txt"
    receipt = root / "commit-receipt.json"
    artifact.write_text("before\n", encoding="utf-8")

    with pytest.raises(LeaseLostError, match="expired"):
        with store.commit_guard(lease, ["artifact.txt"]):
            artifact.write_text("write-in-progress\n", encoding="utf-8")
            now[0] = 106.0
        receipt.write_text("committed\n", encoding="utf-8")

    assert not receipt.exists()
    with pytest.raises(LeaseLostError, match="expired"):
        store.assert_current(lease, ["artifact.txt"])


def test_rooted_scope_resolves_symlink_alias_to_same_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "real").mkdir(parents=True)
    (root / "real" / "file.py").write_text("", encoding="utf-8")
    alias = root / "alias"
    try:
        alias.symlink_to(root / "real", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    assert normalize_paths(["alias/file.py"], root=root) == normalize_paths(
        ["real/file.py"], root=root
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction reparse points are platform-specific")
def test_rooted_scope_resolves_junction_alias_to_same_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    real = root / "real"
    real.mkdir(parents=True)
    (real / "file.py").write_text("", encoding="utf-8")
    alias = root / "junction"
    created = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(alias), str(real)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"junction creation unavailable: {created.stderr or created.stdout}")
    try:
        assert alias.is_junction()
        assert normalize_paths(["junction/file.py"], root=root) == normalize_paths(
            ["real/file.py"], root=root
        )
    finally:
        alias.rmdir()


def test_expiry_reacquire_fences_stale_write_and_commit_without_side_effects(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "source.txt"
    journal = tmp_path / "journal.json"
    source.write_text("before\n", encoding="utf-8")
    journal.write_text("prepared-old\n", encoding="utf-8")
    now = [100.0]
    store = FencingLeaseStore(tmp_path / "fences.sqlite3", clock=lambda: now[0])

    stale_attempt = store.claim_attempt(
        str(root), "work-1", "owner-a", ttl_seconds=5
    )
    stale = store.acquire(
        str(root), "owner-a", ["source.txt"], ttl_seconds=30,
        attempt=stale_attempt,
    )
    now[0] = 106.0
    current_attempt = store.claim_attempt(
        str(root), "work-1", "owner-b", ttl_seconds=30
    )
    current = store.acquire(
        str(root), "owner-b", ["source.txt"], ttl_seconds=30,
        attempt=current_attempt,
    )
    assert current.fencing_token > stale.fencing_token
    assert current_attempt.fencing_token > stale_attempt.fencing_token

    with pytest.raises(LeaseLostError):
        with store.commit_guard(stale, ["source.txt"]):
            source.write_text("stale-write\n", encoding="utf-8")
            journal.write_text("stale-commit\n", encoding="utf-8")
    with pytest.raises(LeaseLostError):
        store.acquire(
            str(root), "owner-a", ["source.txt"], ttl_seconds=30,
            attempt=stale_attempt,
        )

    assert source.read_text(encoding="utf-8") == "before\n"
    assert journal.read_text(encoding="utf-8") == "prepared-old\n"
    with store.commit_guard(current, ["source.txt"]):
        source.write_text("current-write\n", encoding="utf-8")
        journal.write_text("committed-current\n", encoding="utf-8")
    assert source.read_text(encoding="utf-8") == "current-write\n"
    assert journal.read_text(encoding="utf-8") == "committed-current\n"


def test_stale_owner_cannot_renew_or_release_reacquired_lease(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    now = [10.0]
    store = FencingLeaseStore(tmp_path / "fences.sqlite3", clock=lambda: now[0])
    stale_attempt = store.claim_attempt(str(root), "work-2", "owner-a", ttl_seconds=2)
    stale = store.acquire(
        str(root), "owner-a", ["a.py"], ttl_seconds=30, attempt=stale_attempt
    )
    now[0] = 13.0
    current_attempt = store.claim_attempt(str(root), "work-2", "owner-b", ttl_seconds=30)
    current = store.acquire(
        str(root), "owner-b", ["a.py"], ttl_seconds=30, attempt=current_attempt
    )

    with pytest.raises(LeaseLostError):
        store.renew(stale, ttl_seconds=30)
    assert store.release(stale) is False
    with pytest.raises(LeaseLostError):
        store.renew_attempt(stale_attempt, ttl_seconds=30)
    store.release_attempt(stale_attempt)
    store.assert_current(current, ["a.py"])


def test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens(
    tmp_path: Path,
) -> None:
    import json
    import subprocess
    import sys

    root = tmp_path / "repo"
    root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    receipt_path = tmp_path / "fence-receipt.json"
    output = root / "artifact.txt"
    script = r"""
import json
import pathlib
import sys
from dataclasses import asdict
from local_ai_hub.work_fencing import FencingLease, FencingLeaseStore, LeaseLostError, WorkAttemptFence

mode, root_s, state_s, receipt_s = sys.argv[1:]
root = pathlib.Path(root_s)
db = pathlib.Path(state_s) / "work_fencing.sqlite3"
receipt = pathlib.Path(receipt_s)
if mode == "old":
    store = FencingLeaseStore(db, clock=lambda: 100.0)
    attempt = store.claim_attempt(root, "work-subprocess", "old-writer", ttl_seconds=5)
    lease = store.acquire(root, "old-writer", ["artifact.txt"], ttl_seconds=30, attempt=attempt)
    receipt.write_text(json.dumps({
        "attempt": asdict(attempt),
        "lease": {**asdict(lease), "paths": list(lease.paths)},
    }), encoding="utf-8")
elif mode == "successor":
    store = FencingLeaseStore(db, clock=lambda: 106.0)
    old = json.loads(receipt.read_text(encoding="utf-8"))
    current_attempt = store.claim_attempt(root, "work-subprocess", "new-writer", ttl_seconds=30)
    current_lease = store.acquire(root, "new-writer", ["artifact.txt"], ttl_seconds=30, attempt=current_attempt)
    output = root / "artifact.txt"
    commit_receipt = root / "commit-receipt.json"
    with store.commit_guard(current_lease, ["artifact.txt"]):
        store.assert_current(current_lease, ["artifact.txt"])
        output.write_text("successor\n", encoding="utf-8")
        commit_receipt.write_text(json.dumps({"owner": "new-writer", "token": current_attempt.fencing_token}), encoding="utf-8")
    proof = {
        "resource": str(root),
        "work_id": "work-subprocess",
        "database": str(db),
        "attempt_scope": current_attempt.scope_id,
        "lease_scope": current_lease.scope_id,
        "attempt_token": current_attempt.fencing_token,
        "path_token": current_lease.fencing_token,
    }
    (pathlib.Path(state_s) / "successor-receipt.json").write_text(
        json.dumps(proof), encoding="utf-8"
    )
    print(json.dumps(proof))
elif mode == "stale":
    store = FencingLeaseStore(db, clock=lambda: 106.0)
    old = json.loads(receipt.read_text(encoding="utf-8"))
    old_attempt = WorkAttemptFence(**old["attempt"])
    old_lease_data = dict(old["lease"])
    old_lease_data["paths"] = tuple(old_lease_data["paths"])
    old_lease = FencingLease(**old_lease_data)
    output = root / "artifact.txt"
    commit_receipt = root / "commit-receipt.json"
    try:
        store.assert_attempt_current(old_attempt)
        stale_attempt_rejected = False
    except LeaseLostError:
        stale_attempt_rejected = True
    try:
        with store.commit_guard(old_lease, ["artifact.txt"]):
            output.write_text("stale\n", encoding="utf-8")
            commit_receipt.write_text("stale commit", encoding="utf-8")
        stale_commit_rejected = False
    except LeaseLostError:
        stale_commit_rejected = True
    proof = {
        "stale_attempt_scope": old_attempt.scope_id,
        "stale_lease_scope": old_lease.scope_id,
        "stale_attempt_token": old_attempt.fencing_token,
        "stale_path_token": old_lease.fencing_token,
        "stale_attempt_rejected": stale_attempt_rejected,
        "stale_commit_rejected": stale_commit_rejected,
        "output": output.read_text(encoding="utf-8"),
        "commit_receipt": commit_receipt.read_text(encoding="utf-8"),
    }
    (pathlib.Path(state_s) / "stale-receipt.json").write_text(
        json.dumps(proof), encoding="utf-8"
    )
    print(json.dumps(proof))
else:
    raise ValueError("unknown mode")
"""
    project_root = Path(__file__).resolve().parents[1]

    def run_process(mode: str) -> str:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                script,
                mode,
                str(root),
                str(state_dir),
                str(receipt_path),
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        return result.stdout.strip()

    run_process("old")
    result = json.loads(run_process("successor"))
    stale = json.loads(run_process("stale"))
    persisted_receipt = json.loads(
        (state_dir / "successor-receipt.json").read_text(encoding="utf-8")
    )

    assert persisted_receipt == result
    assert result["resource"] == str(root)
    assert result["work_id"] == "work-subprocess"
    assert result["database"] == str(state_dir / "work_fencing.sqlite3")
    physical_scope = os.path.normcase(str(root.resolve()))
    assert result["attempt_scope"] == physical_scope
    assert result["lease_scope"] == physical_scope
    assert stale["stale_attempt_scope"] == physical_scope
    assert stale["stale_lease_scope"] == physical_scope
    assert result["attempt_token"] > stale["stale_attempt_token"]
    assert result["path_token"] > stale["stale_path_token"]
    assert stale["stale_attempt_rejected"] is True
    assert stale["stale_commit_rejected"] is True
    assert stale["output"] == "successor\n"
    assert json.loads(stale["commit_receipt"]) == {
        "owner": "new-writer",
        "token": result["attempt_token"],
    }
    assert output.read_text(encoding="utf-8") == "successor\n"
