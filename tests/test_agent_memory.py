from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import (
    ApprovalRequiredError,
    MemoryKind,
    MemoryRecord,
    MemoryStatus,
    MemoryStore,
)
from local_ai_hub.sqlite_support import connect_sqlite


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    return MemoryStore(state_store)


def model_conclusion(scope: AgentScope = AgentScope.TASK) -> MemoryRecord:
    return MemoryRecord.create(
        kind=MemoryKind.HYPOTHESIS,
        scope=scope,
        key="parser_behavior",
        value={"issue": "unexpected token"},
        confidence=0.75,
        source="model",
    )


def confirmed_repository_record(store: MemoryStore) -> MemoryRecord:
    rec = MemoryRecord.create(
        kind=MemoryKind.CONVENTION,
        scope=AgentScope.REPOSITORY,
        key="style",
        value="black",
        confidence=0.95,
        source="user",
        status=MemoryStatus.CONFIRMED,
    )
    return store.record(rec, actor="user", idempotency_key="rec-repo-1")


def test_model_conclusion_is_candidate_not_repository_memory(store: MemoryStore):
    record = store.record(model_conclusion(scope=AgentScope.TASK), actor="agent", idempotency_key="m1")
    assert record.status is MemoryStatus.CANDIDATE


def test_legacy_unscoped_lookup_rejects_nonempty_task_and_session_context(store: MemoryStore):
    legacy_task = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        key="legacy-task",
        value="must not leak",
    )
    scoped_task = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-1",
        key="scoped-task",
        value="task value",
    )
    legacy_session = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        key="legacy-session",
        value="must not leak",
    )
    scoped_session = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="session-1",
        key="scoped-session",
        value="session value",
    )
    for record in (legacy_task, scoped_task, legacy_session, scoped_session):
        store.record(record, actor="user")

    assert [record.value for record in store.find(scope=AgentScope.TASK)] == ["must not leak"]
    assert [record.value for record in store.find(scope=AgentScope.SESSION)] == ["must not leak"]
    assert [record.value for record in store.find(allow_legacy_unscoped=True, task_id="task-1")] == ["task value"]
    assert [record.value for record in store.find(allow_legacy_unscoped=True, session_id="session-1")] == ["session value"]
    assert store.find(scope=AgentScope.TASK, root="C:/repo") == []
    assert store.find(scope=AgentScope.SESSION, tenant="tenant-1") == []
    assert store.get(legacy_task.record_id, task_id="task-1") is None
    assert store.get(scoped_task.record_id, task_id="task-1").value == "task value"


def test_memory_find_enforces_root_repository_and_tenant_identity(store: MemoryStore):
    repo_a = store.record(MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="shared-repo",
        value="repo-a",
        provenance={"root": "C:/repo-a", "repository_id": "repo-a"},
    ))
    repo_b = store.record(MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="shared-repo",
        value="repo-b",
        provenance={"root": "C:/repo-b", "repository_id": "repo-b"},
    ))
    repo_missing_id = store.record(MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="shared-repo",
        value="repo-missing-id",
        provenance={"root": "C:/repo-a"},
    ))
    tenant_one = store.record(MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="tenant-1",
        key="shared-tenant",
        value="tenant-1",
        provenance={"tenant": "tenant-1"},
    ))
    tenant_two = store.record(MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.SESSION,
        scope_id="tenant-2",
        key="shared-tenant",
        value="tenant-2",
        provenance={"tenant": "tenant-2"},
    ))
    rich_task = store.record(MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-rich",
        key="rich-task",
        value="rich",
        provenance={
            "root": "C:/repo-rich",
            "repository_id": "repo-rich",
            "clone_id": "clone-rich",
            "worktree_id": "worktree-rich",
            "branch": "branch-rich",
        },
    ))

    assert {record.record_id for record in store.find(scope=AgentScope.REPOSITORY, root="C:/repo-a", key="shared-repo")} == {
        repo_a.record_id,
        repo_missing_id.record_id,
    }
    assert [record.record_id for record in store.find(scope=AgentScope.REPOSITORY, root="C:/repo-b", key="shared-repo")] == [repo_b.record_id]
    assert [record.record_id for record in store.find(scope=AgentScope.REPOSITORY, repository_id="repo-a", key="shared-repo")] == [repo_a.record_id]
    assert [record.record_id for record in store.find(scope=AgentScope.SESSION, scope_id="tenant-1", tenant="tenant-1", key="shared-tenant")] == [tenant_one.record_id]
    assert [record.record_id for record in store.find(scope=AgentScope.SESSION, scope_id="tenant-2", tenant="tenant-2", key="shared-tenant")] == [tenant_two.record_id]
    assert [record.record_id for record in store.find(
        scope=AgentScope.TASK,
        task_id="task-rich",
        clone_id="clone-rich",
        worktree_id="worktree-rich",
        branch="branch-rich",
        root="C:/repo-rich",
        repository_id="repo-rich",
        key="rich-task",
    )] == [rich_task.record_id]
    assert store.find(
        scope=AgentScope.TASK,
        task_id="task-rich",
        clone_id="wrong-clone",
        worktree_id="worktree-rich",
        branch="branch-rich",
        root="C:/repo-rich",
        repository_id="repo-rich",
        key="rich-task",
    ) == []


def test_memory_identity_indexes_exist_for_bounded_filtered_queries(store: MemoryStore):
    con = connect_sqlite(store.state_store.db_path)
    try:
        names = {str(row[1]) for row in con.execute("PRAGMA index_list(agent_memory_records)").fetchall()}
    finally:
        con.close()
    assert {
        "idx_agent_memory_scope_identity",
        "idx_agent_memory_provenance_root",
        "idx_agent_memory_provenance_repository",
        "idx_agent_memory_provenance_tenant",
        "idx_agent_memory_provenance_clone_id",
        "idx_agent_memory_provenance_worktree_id",
        "idx_agent_memory_provenance_branch",
    } <= names


def test_memory_query_limit_is_hard_capped(store: MemoryStore):
    for index in range(101):
        store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.GLOBAL,
                key=f"bounded-{index}",
                value=index,
            ),
            idempotency_key=f"bounded-{index}",
        )

    store.max_query_limit = 10_000
    assert len(store.find(scope=AgentScope.GLOBAL, limit=100_000)) == 100
    with pytest.raises(ValueError, match="memory limit"):
        store.find(scope=AgentScope.GLOBAL, limit="invalid")


def test_global_promotion_requires_user_approval(store: MemoryStore):
    record = confirmed_repository_record(store)
    with pytest.raises(ApprovalRequiredError):
        store.promote(record.record_id, AgentScope.GLOBAL, approver="agent")


def test_global_promotion_succeeds_with_user_approval(store: MemoryStore):
    record = confirmed_repository_record(store)
    promoted = store.promote(record.record_id, AgentScope.GLOBAL, approver="user")
    assert promoted.scope is AgentScope.GLOBAL
    assert promoted.status is MemoryStatus.CONFIRMED


def test_conflicting_high_confidence_records_are_quarantined(store: MemoryStore):
    r1 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="database_port",
        value=5432,
        confidence=0.95,
        source="config",
        status=MemoryStatus.CONFIRMED,
    )
    store.record(r1, actor="user", idempotency_key="r1")

    r2 = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="database_port",
        value=3306,
        confidence=0.90,
        source="log",
        status=MemoryStatus.CONFIRMED,
    )
    saved_r2 = store.record(r2, actor="user", idempotency_key="r2")
    assert saved_r2.status is MemoryStatus.QUARANTINED
    assert "conflict" in (saved_r2.quarantine_reason or "").lower()


@pytest.mark.parametrize("scope", [AgentScope.TASK, AgentScope.SESSION])
def test_conflicts_are_isolated_by_scope_id(store: MemoryStore, scope: AgentScope):
    first = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=scope,
            scope_id="scope-one",
            key="isolated-key",
            value="one",
            confidence=0.95,
            status=MemoryStatus.CONFIRMED,
        ),
        actor="user",
        idempotency_key=f"{scope.value}-one",
    )
    second = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=scope,
            scope_id="scope-two",
            key="isolated-key",
            value="two",
            confidence=0.95,
            status=MemoryStatus.CONFIRMED,
        ),
        actor="user",
        idempotency_key=f"{scope.value}-two",
    )

    assert first.status is MemoryStatus.CONFIRMED
    assert second.status is MemoryStatus.CONFIRMED


def test_repository_conflicts_are_isolated_by_root(store: MemoryStore, tmp_path: Path):
    root_one = tmp_path / "repo-one"
    root_two = tmp_path / "repo-two"
    root_one.mkdir()
    root_two.mkdir()
    for root, value, key in ((root_one, "one", "repo-one"), (root_two, "two", "repo-two")):
        record = store.record(
            MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.REPOSITORY,
                scope_id=key,
                key="root-isolated-key",
                value=value,
                confidence=0.95,
                status=MemoryStatus.CONFIRMED,
                provenance={"root": str(root)},
            ),
            actor="user",
            idempotency_key=key,
        )
        assert record.status is MemoryStatus.CONFIRMED


def test_task_conflicts_are_isolated_by_provenance_root(store: MemoryStore, tmp_path: Path):
    for index in range(2):
        record = store.record(
            MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.TASK,
                scope_id="same-task",
                key="root-aware-task-key",
                value=index,
                confidence=0.95,
                status=MemoryStatus.CONFIRMED,
                provenance={"root": str(tmp_path / f"repo-{index}")},
            ),
            idempotency_key=f"root-aware-task-{index}",
        )
        assert record.status is MemoryStatus.CONFIRMED


def test_consistency_memory_kinds_round_trip():
    kinds = (
        MemoryKind.FINDING,
        MemoryKind.REUSABLE_CANDIDATE,
        MemoryKind.CONTRACT_MAPPING,
        MemoryKind.REJECTED_APPROACH,
        MemoryKind.UNKNOWN,
        MemoryKind.VALIDATION,
    )
    for kind in kinds:
        record = MemoryRecord.create(kind=kind, scope=AgentScope.TASK, key=kind.value, value={"kind": kind.value})
        restored = MemoryRecord.from_dict(record.to_dict())
        assert restored.kind is kind


def test_record_idempotency_reuses_existing_record(store: MemoryStore):
    first = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            key="same-request",
            value="first",
            scope_id="task-1",
        ),
        actor="agent",
        idempotency_key="memory-request-1",
    )
    second = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.TASK,
            key="same-request",
            value="second",
            scope_id="task-1",
        ),
        actor="agent",
        idempotency_key="memory-request-1",
    )

    assert second.record_id == first.record_id
    assert store.count() == 1
    assert [event.kind for event in store.state_store.events(
        stream_id=f"memory:{AgentScope.TASK.value}:same-request"
    )].count("memory.recorded") == 1


def test_record_idempotency_is_atomic_under_concurrency(store: MemoryStore):
    def record_attempt(index: int) -> str:
        saved = store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.TASK,
                key="concurrent",
                value=index,
                scope_id="task-concurrent",
            ),
            actor="agent",
            idempotency_key="memory-concurrent-1",
        )
        return saved.record_id

    with ThreadPoolExecutor(max_workers=4) as executor:
        record_ids = list(executor.map(record_attempt, range(4)))

    assert len(set(record_ids)) == 1
    assert store.count() == 1
    assert [event.kind for event in store.state_store.events(
        stream_id=f"memory:{AgentScope.TASK.value}:concurrent"
    )].count("memory.recorded") == 1


def test_conflicting_high_confidence_insert_is_atomic_under_concurrency(tmp_path: Path):
    db_path = tmp_path / "agent_state.sqlite3"
    stores = [
        MemoryStore(AgentStateStore(db_path)),
        MemoryStore(AgentStateStore(db_path)),
    ]

    def record_attempt(index: int) -> MemoryRecord:
        return stores[index].record(
            MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.REPOSITORY,
                scope_id="repo",
                key="concurrent-conflict",
                value=index,
                confidence=0.95,
                status=MemoryStatus.CONFIRMED,
                provenance={"root": str(tmp_path / "repo")},
            ),
            actor="agent",
            idempotency_key=f"conflict-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        saved = list(executor.map(record_attempt, range(2)))

    assert sum(item.status in (MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED) for item in saved) == 1
    assert sum(item.status is MemoryStatus.QUARANTINED for item in saved) == 1

def test_repository_revision_is_preserved_in_provenance(store: MemoryStore, tmp_path: Path):
    record = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="parser",
        value="uses Pratt parsing",
        provenance={
            "root": str(tmp_path),
            "repository_revision": "rev-1",
            "path_refs": ["src/parser.py"],
            "symbol_refs": ["Parser.parse"],
            "related_task": "task-1",
        },
    )

    saved = store.record(record)
    restored = store.get(saved.record_id)

    assert restored is not None
    assert restored.repository_revision == "rev-1"
    assert restored.path_refs == ("src/parser.py",)
    assert restored.symbol_refs == ("Parser.parse",)
    assert restored.provenance["related_task"] == "task-1"


def test_mark_stale_for_revision_preserves_metadata_and_emits_event(store: MemoryStore, tmp_path: Path):
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="parser",
            value="old evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "root": str(tmp_path),
                "repository_revision": "rev-1",
                "path_refs": ["src/parser.py"],
            },
        )
    )

    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/parser.py"]) == 1

    stale = store.get(record.record_id)
    assert stale is not None
    assert stale.status is MemoryStatus.STALE
    assert stale.provenance["repository_revision"] == "rev-1"
    assert stale.provenance["staled_by_revision"] == "rev-2"
    assert stale.provenance["superseded_metadata"]["status"] == "confirmed"
    assert any(event.kind == "memory.staled" for event in store.state_store.events(
        stream_id=f"memory:{AgentScope.REPOSITORY.value}:parser"
    ))


def test_mark_stale_for_revision_guards_revision_paths_root_and_repeats(store: MemoryStore, tmp_path: Path):
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="guarded",
            value="evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "root": str(tmp_path),
                "repository_revision": "rev-1",
                "path_refs": ["src/guarded.py"],
            },
        )
    )

    assert store.mark_stale_for_revision(str(tmp_path), "rev-1", ["src/guarded.py"]) == 0
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/other.py"]) == 0
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["other/src/guarded.py"]) == 0
    assert store.mark_stale_for_revision(str(tmp_path / "other"), "rev-2", ["src/guarded.py"]) == 0
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", None) == 0

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda _: store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/guarded.py"]),
            range(2),
        ))

    assert sorted(results) == [0, 1]
    events = store.state_store.events(stream_id=f"memory:{AgentScope.REPOSITORY.value}:guarded")
    assert [event.kind for event in events].count("memory.staled") == 1
    assert store.get(record.record_id).status is MemoryStatus.STALE


def test_mark_stale_for_revision_matches_beyond_100k_rows(store: MemoryStore, tmp_path: Path):
    root = str(tmp_path)
    rows = [
        (
            f"bulk-{index}",
            MemoryKind.FINDING.value,
            AgentScope.REPOSITORY.value,
            "",
            f"bulk-{index}",
            json.dumps("unrelated"),
            MemoryStatus.CONFIRMED.value,
            1.0,
            "agent",
            "[]",
            "normal",
            None,
            None,
            None,
            json.dumps({"root": root, "repository_revision": "rev-1", "path_refs": [f"src/other-{index}.py"]}),
            float(index + 2),
            float(index + 2),
            None,
        )
        for index in range(100_000)
    ]
    rows.append(
        (
            "bulk-match",
            MemoryKind.FINDING.value,
            AgentScope.REPOSITORY.value,
            "",
            "bulk-match",
            json.dumps("matching"),
            MemoryStatus.CONFIRMED.value,
            1.0,
            "agent",
            "[]",
            "normal",
            None,
            None,
            None,
            json.dumps({"root": root, "repository_revision": "rev-1", "path_refs": ["src/match.py"]}),
            1.0,
            1.0,
            None,
        )
    )
    con = connect_sqlite(store.state_store.db_path)
    try:
        con.executemany(
            """
            INSERT INTO agent_memory_records (
                record_id, kind, scope, scope_id, key, value, status, confidence, source,
                evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id,
                quarantine_reason, provenance, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()
    finally:
        con.close()

    assert store.mark_stale_for_revision(root, "rev-2", ["src/match.py"]) == 1
    assert store.get("bulk-match").status is MemoryStatus.STALE


def test_mark_stale_for_revision_matches_relative_and_absolute_roots(store: MemoryStore, tmp_path: Path):
    relative_root = os.path.relpath(tmp_path, Path.cwd())
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="relative-root",
            value="evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "root": relative_root,
                "repository_revision": "rev-1",
                "path_refs": ["src/relative.py"],
            },
        )
    )

    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/relative.py"]) == 1
    assert store.get(record.record_id).status is MemoryStatus.STALE


def test_mark_stale_for_revision_deduplicates_and_caps_changed_paths(store: MemoryStore, tmp_path: Path):
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope=AgentScope.REPOSITORY,
            key="bounded-paths",
            value="evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={
                "root": str(tmp_path),
                "repository_revision": "rev-1",
                "path_refs": ["src/match.py"],
            },
        )
    )
    changed_paths = [None, "None", "src/match.py", "src/match.py"] + [
        f"src/other-{index}.py" for index in range(64)
    ]

    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", changed_paths) == 1
    stale = store.get(record.record_id)
    assert stale is not None
    bounded_paths = stale.provenance["staled_changed_paths"]
    assert len(bounded_paths) == 32
    assert len(set(bounded_paths)) == len(bounded_paths)
    assert "None" not in bounded_paths


def test_mark_stale_batch_rolls_back_and_repeats_idempotently(store: MemoryStore, tmp_path: Path, monkeypatch):
    records = [
        store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.REPOSITORY,
                key=f"batch-{index}",
                value="evidence",
                status=MemoryStatus.CONFIRMED,
                provenance={
                    "root": str(tmp_path),
                    "repository_revision": "rev-1",
                    "path_refs": [f"src/batch-{index}.py"],
                },
            )
        )
        for index in range(2)
    ]
    original_create = AgentEvent.create
    calls = 0

    def fail_on_second_create(cls, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected batch failure")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(AgentEvent, "create", classmethod(fail_on_second_create))
    with pytest.raises(RuntimeError, match="injected batch failure"):
        store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/batch-0.py", "src/batch-1.py"])

    assert [store.get(record.record_id).status for record in records] == [
        MemoryStatus.CONFIRMED,
        MemoryStatus.CONFIRMED,
    ]
    assert all(
        not [event for event in store.state_store.events(
            stream_id=f"memory:{AgentScope.REPOSITORY.value}:batch-{index}"
        ) if event.kind == "memory.staled"]
        for index in range(2)
    )

    count = store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/batch-0.py", "src/batch-1.py"])
    assert count == 2
    assert store.mark_stale_for_revision(str(tmp_path), "rev-2", ["src/batch-0.py", "src/batch-1.py"]) == 0
