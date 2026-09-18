from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
