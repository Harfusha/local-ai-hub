from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.cache import SQLiteCache
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.leases import ScopeLeaseStore


def _assert_task_memory_access(store: MemoryStore, memory: MemoryRecord, task_id: str) -> None:
    assert store.get(
        memory.record_id,
        scope=memory.scope,
        scope_id=task_id,
    ) is None
    restored = store.get(
        memory.record_id,
        scope=memory.scope,
        scope_id=task_id,
        task_id=task_id,
        root=memory.provenance["root"],
    )
    assert restored is not None
    assert restored.value == memory.value


@pytest.mark.parametrize("derived_db", ["cache", "code-index"])
def test_derived_sqlite_recovery_preserves_agent_state_and_leases(tmp_path, derived_db):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    repository = tmp_path / "repository"
    repository.mkdir()

    state = AgentStateStore(state_dir / "agent_state.sqlite")
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="preserve durable state", acceptance_criteria=("receipt",)),
        ScopeContext(task_id="t05-durable-task"),
        task_id="t05-durable-task",
    )
    event = AgentEvent.create(task.task_id, "task.created", {"goal": task.contract.goal}, "t05-event")
    state.append(event)

    memories = MemoryStore(state)
    memory = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        key="durable-marker",
        value="keep across derived database recovery",
        source="test",
        provenance={"root": str(repository)},
    )
    memories._save_record(memory)

    verifications = VerificationStore(state, task_store=tasks)
    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="receipt",
        passed=True,
        expires_at=None,
        evidence_id="t05-durable-evidence",
    )
    verifications.record(receipt)

    leases = ScopeLeaseStore(state_dir)
    lease = leases.claim(
        owner="t05", root=str(repository), paths=["src/durable.py"],
        purpose="persistence test",
    )
    assert lease["success"] is True

    derived_name = "cache.sqlite3" if derived_db == "cache" else "code-index.sqlite3"
    derived_path = state_dir / derived_name
    assert derived_path.resolve() != state.db_path.resolve()
    derived_path.write_bytes(b"corrupt disposable database")

    if derived_db == "cache":
        SQLiteCache(derived_path, "t05-persistence-test")
    else:
        CodeIndex({"server": {"state_dir": str(state_dir)}}, repo_tools=None)

    with closing(sqlite3.connect(derived_path)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert list(state_dir.glob(f"{derived_name}.corrupt-*"))

    # Reopen every durable store to model a Hub restart after derived DB recovery.
    reopened_state = AgentStateStore(state_dir / "agent_state.sqlite")
    reopened_tasks = TaskStore(reopened_state)
    reopened_memories = MemoryStore(reopened_state)
    reopened_verifications = VerificationStore(reopened_state, task_store=reopened_tasks)
    reopened_leases = ScopeLeaseStore(state_dir)

    assert reopened_tasks.get(task.task_id).contract.goal == "preserve durable state"
    assert reopened_state.events(task.task_id) == [event.with_seq(1)]
    _assert_task_memory_access(reopened_memories, memory, task.task_id)
    with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as connection:
        assert connection.execute(
            "SELECT receipt_id FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone() == (receipt.receipt_id,)
    assert reopened_leases.list(str(repository))[0]["lease_id"] == lease["lease_id"]
    assert (state_dir / "agent_state.sqlite").is_file()
    assert not list(state_dir.glob("agent_state.sqlite.corrupt-*"))


def test_scoped_memory_delete_preserves_all_relations_until_authorized(tmp_path):
    state = AgentStateStore(tmp_path / "agent_state.sqlite")
    memories = MemoryStore(state)
    root = tmp_path / "repository"
    root.mkdir()
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
        key="identity-marker",
        value="keep until owner deletes",
        source="test",
        provenance={"root": str(root), "worktree_id": "t05-worktree"},
    )
    memories._save_record(record)
    related = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
        key="related-marker",
        value="linked memory",
        source="test",
        provenance={"root": str(root), "worktree_id": "t05-worktree"},
    )
    memories._save_record(related)
    memories.record_relation(record.record_id, "relates_to", related.record_id)
    original_relations = memories.find_relations(source_entity=record.record_id)
    assert original_relations

    assert memories.delete(record.record_id) is False
    assert memories.delete(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="another-worktree",
        root=str(root),
        worktree_id="another-worktree",
    ) is False
    assert memories.delete(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
        worktree_id="t05-worktree",
    ) is False
    assert memories.get(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
    ) is None
    assert memories.get(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
        root=str(root),
        worktree_id="t05-worktree",
    ).value == "keep until owner deletes"
    assert memories.find_relations(source_entity=record.record_id) == original_relations

    assert memories.delete(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
        root=str(root),
        worktree_id="t05-worktree",
    ) is True
    assert memories.get(
        record.record_id,
        scope=AgentScope.WORKTREE,
        scope_id="t05-worktree",
        root=str(root),
        worktree_id="t05-worktree",
    ) is None
    assert memories.find_relations(source_entity=record.record_id) == []


def test_sqlite_cache_recovers_corruption_after_first_initialization(tmp_path):
    cache_path = tmp_path / "cache.sqlite3"
    cache = SQLiteCache(cache_path, "t05-post-init-recovery")
    cache.set("before-corruption", {"value": "discarded derived data"})

    cache_path.write_bytes(b"corrupt after successful initialization")

    assert cache.get("before-corruption") is None
    assert list(tmp_path.glob("cache.sqlite3.corrupt-*"))
    with closing(sqlite3.connect(cache_path)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    cache.set("after-recovery", {"value": "cache operational"})
    assert cache.get("after-recovery") == {"value": "cache operational"}


def test_cache_rebuild_failure_keeps_durable_state_intact_and_retries(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    durable_path = state_dir / "agent_state.sqlite"
    state = AgentStateStore(durable_path)
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="survive failed cache rebuild", acceptance_criteria=("event",)),
        ScopeContext(task_id="t05-cache-rebuild-failure"),
        task_id="t05-cache-rebuild-failure",
    )
    event = AgentEvent.create(
        task.task_id,
        "cache.rebuild.sentinel",
        {"durable": True},
        "t05-cache-rebuild-event",
    )
    state.append(event)
    with closing(sqlite3.connect(durable_path)) as connection:
        connection.execute(
            "INSERT INTO agent_snapshots(stream_id, seq, state, created_at) VALUES (?, ?, ?, ?)",
            (task.task_id, 1, '{"durable":true}', 1.0),
        )
        connection.commit()

    cache_path = state_dir / "cache.sqlite3"
    cache_path.write_bytes(b"corrupt disposable cache")
    durable_files = tuple(
        path.read_bytes() if path.is_file() else None
        for path in (durable_path, Path(f"{durable_path}-wal"), Path(f"{durable_path}-shm"))
    )
    original_create_schema = SQLiteCache._create_schema
    create_attempts = 0

    def fail_rebuild_after_quarantine(cache):
        nonlocal create_attempts
        create_attempts += 1
        if create_attempts == 1:
            return original_create_schema(cache)
        raise sqlite3.OperationalError("injected cache schema rebuild failure")

    monkeypatch.setattr(SQLiteCache, "_create_schema", fail_rebuild_after_quarantine)
    with pytest.raises(sqlite3.OperationalError, match="injected cache schema rebuild failure"):
        SQLiteCache(cache_path, "t05-rebuild-failure")

    assert create_attempts == 2
    quarantined = list(state_dir.glob("cache.sqlite3.corrupt-*"))
    assert len(quarantined) == 1
    assert not list(state_dir.glob("agent_state.sqlite.corrupt-*"))
    assert tuple(
        path.read_bytes() if path.is_file() else None
        for path in (durable_path, Path(f"{durable_path}-wal"), Path(f"{durable_path}-shm"))
    ) == durable_files

    monkeypatch.setattr(SQLiteCache, "_create_schema", original_create_schema)
    cache = SQLiteCache(cache_path, "t05-rebuild-failure")
    cache.set("after-retry", {"ready": True})
    assert cache.get("after-retry") == {"ready": True}
    reopened = AgentStateStore(durable_path)
    assert TaskStore(reopened).get(task.task_id).contract.goal == "survive failed cache rebuild"
    assert reopened.events(task.task_id) == [event.with_seq(1)]
    with closing(sqlite3.connect(durable_path)) as connection:
        assert connection.execute(
            "SELECT state FROM agent_snapshots WHERE stream_id=? AND seq=1", (task.task_id,)
        ).fetchone()[0] == '{"durable":true}'


def test_process_crash_after_cache_rebuild_preserves_durable_agent_state(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state = AgentStateStore(state_dir / "agent_state.sqlite")
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="survive cache rebuild crash", acceptance_criteria=("receipt",)),
        ScopeContext(task_id="t05-cache-crash"),
        task_id="t05-cache-crash",
    )
    events_before = state.events(task.task_id)
    memories = MemoryStore(state)
    memory = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        key="crash-marker",
        value="keep after cache rebuild crash",
        source="test",
        provenance={"root": str(state_dir)},
    )
    memories._save_record(memory)
    verifications = VerificationStore(state, task_store=tasks)
    receipt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="receipt",
        passed=True,
        expires_at=None,
        evidence_id="t05-cache-crash-evidence",
    )
    verifications.record(receipt)

    cache_path = state_dir / "cache.sqlite3"
    cache_path.write_bytes(b"corrupt disposable database")
    recovery_script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from local_ai_hub.cache import SQLiteCache\n"
        "SQLiteCache(Path(sys.argv[1]), 't05-crash-recovery')\n"
        "os._exit(73)\n"
    )
    child = subprocess.run(
        [sys.executable, "-c", recovery_script, str(cache_path)],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert child.returncode == 73, child.stderr.decode(errors="replace")

    reopened_state = AgentStateStore(state_dir / "agent_state.sqlite")
    reopened_tasks = TaskStore(reopened_state)
    reopened_memories = MemoryStore(reopened_state)
    reopened_verifications = VerificationStore(reopened_state, task_store=reopened_tasks)
    assert reopened_tasks.get(task.task_id).contract.goal == task.contract.goal
    assert reopened_state.events(task.task_id) == events_before
    _assert_task_memory_access(reopened_memories, memory, task.task_id)
    with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as connection:
        assert connection.execute(
            "SELECT receipt_id FROM agent_verification_receipts WHERE receipt_id = ?",
            (receipt.receipt_id,),
        ).fetchone() == (receipt.receipt_id,)


@pytest.mark.parametrize("derived_db", ["cache", "code-index"])
def test_concurrent_derived_recovery_preserves_durable_agent_state(tmp_path, derived_db):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state = AgentStateStore(state_dir / "agent_state.sqlite3")
    tasks = TaskStore(state)
    task = tasks.create(
        GoalContract(goal="survive concurrent derived recovery", acceptance_criteria=("memory",)),
        ScopeContext(task_id="t05-concurrent-recovery"),
        task_id="t05-concurrent-recovery",
    )
    memories = MemoryStore(state)
    memory = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.TASK,
        scope_id=task.task_id,
        key="concurrent-recovery-marker",
        value="durable memory survives concurrent derived recovery",
        source="test",
        provenance={"root": str(state_dir)},
    )
    memories._save_record(memory)

    derived_name = "cache.sqlite3" if derived_db == "cache" else "code-index.sqlite3"
    derived_path = state_dir / derived_name
    assert derived_path.resolve() != state.db_path.resolve()
    derived_path.write_bytes(b"corrupt derived database")

    barrier = state_dir / "release-workers"
    ready_paths = [state_dir / f"worker-{index}-ready" for index in range(2)]
    recovery_script = (
        "import sqlite3, sys, time\n"
        "from pathlib import Path\n"
        "source_dir, database_kind, database_path, barrier_path, ready_path = sys.argv[1:]\n"
        "sys.path.insert(0, source_dir)\n"
        "ready = Path(ready_path)\n"
        "ready.touch()\n"
        "deadline = time.monotonic() + 20\n"
        "while not Path(barrier_path).exists():\n"
        "    if time.monotonic() >= deadline:\n"
        "        raise TimeoutError('parent did not release recovery workers')\n"
        "    time.sleep(0.01)\n"
        "if database_kind == 'cache':\n"
        "    import local_ai_hub.cache as loaded_module\n"
        "    assert Path(loaded_module.__file__).resolve().is_relative_to(Path(source_dir).resolve())\n"
        "    SQLiteCache = loaded_module.SQLiteCache\n"
        "    SQLiteCache(Path(database_path), 't05-concurrent-recovery')\n"
        "else:\n"
        "    import local_ai_hub.code_index as loaded_module\n"
        "    assert Path(loaded_module.__file__).resolve().is_relative_to(Path(source_dir).resolve())\n"
        "    CodeIndex = loaded_module.CodeIndex\n"
        "    CodeIndex({'server': {'state_dir': str(Path(database_path).parent)}}, repo_tools=None)\n"
        "with sqlite3.connect(database_path) as connection:\n"
        "    assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)\n"
    )
    source_dir = Path(os.environ.get("T05_ROOT_SOURCE_DIR", Path(__file__).resolve().parents[1] / "src")).resolve()
    workers = []
    try:
        for ready_path in ready_paths:
            workers.append(subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    recovery_script,
                    str(source_dir),
                    derived_db,
                    str(derived_path),
                    str(barrier),
                    str(ready_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ))

        deadline = time.monotonic() + 15
        while not all(path.exists() for path in ready_paths):
            exited = [worker for worker in workers if worker.poll() is not None]
            if exited or time.monotonic() >= deadline:
                barrier.touch()
                details = [worker.communicate(timeout=5) for worker in workers]
                raise AssertionError(f"recovery workers failed to rendezvous: {details!r}")
            time.sleep(0.01)
        barrier.touch()
        results = [worker.communicate(timeout=20) for worker in workers]
        assert [worker.returncode for worker in workers] == [0, 0], results
    finally:
        barrier.touch()
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=5)

    with closing(sqlite3.connect(derived_path)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    if derived_db == "cache":
        recovered_cache = SQLiteCache(derived_path, "t05-concurrent-recovery")
        recovered_cache.set("recovered", {"success": True})
        assert recovered_cache.get("recovered") == {"success": True}
    else:
        CodeIndex({"server": {"state_dir": str(state_dir)}}, repo_tools=None)
    reopened_state = AgentStateStore(state_dir / "agent_state.sqlite3")
    reopened_tasks = TaskStore(reopened_state)
    reopened_memories = MemoryStore(reopened_state)
    assert reopened_tasks.get(task.task_id).contract.goal == "survive concurrent derived recovery"
    _assert_task_memory_access(reopened_memories, memory, task.task_id)
