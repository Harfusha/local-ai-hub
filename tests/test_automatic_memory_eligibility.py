from __future__ import annotations

from dataclasses import replace
import pytest

from local_ai_hub import project_config
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore


def test_unconfirmed_consistency_guard_memory_is_management_only(tmp_path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    store = MemoryStore(AgentStateStore(tmp_path / "agent_state.sqlite"))
    coordination_id = project_config.resolve_project_context(
        root, tmp_path / "state"
    ).coordination_id
    assert coordination_id
    provenance = {
        "root": str(root),
        "repository_id": coordination_id,
    }
    with pytest.raises(ValueError, match="retired memory provenance field: tenant identity"):
        MemoryRecord.create(
            kind=MemoryKind.DECISION,
            scope=AgentScope.REPOSITORY,
            key="retired-provenance",
            value="must reject",
            source="consistency_guard",
            provenance={**provenance, "tenant": None},
        )

    legacy_automatic = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.REPOSITORY,
        key="legacy-automatic-guard-decision",
        value={"decision": "reuse", "approved": False},
        status=MemoryStatus.ACTIVE,
        source="consistency_guard",
        provenance=provenance,
    )
    manual_active = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="operator-maintained-memory",
        value="manually maintained active context",
        status=MemoryStatus.ACTIVE,
        source="agent",
        provenance=provenance,
    )
    confirmed_guard_decision = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.REPOSITORY,
        key="confirmed-guard-decision",
        value={"decision": "reuse", "approved": True},
        status=MemoryStatus.CONFIRMED,
        source="consistency_guard",
        provenance=provenance,
    )
    records = (
        replace(legacy_automatic, updated_at=30.0),
        replace(manual_active, updated_at=20.0),
        replace(confirmed_guard_decision, updated_at=10.0),
    )
    for record in records:
        store._save_record(record)

    context_records = store.find_for_context(
        root=str(root),  coordination_id=coordination_id, limit=20
    )
    context_ids = {record.record_id for record in context_records}
    assert legacy_automatic.record_id not in context_ids
    assert manual_active.record_id in context_ids
    assert confirmed_guard_decision.record_id in context_ids

    # Eligibility filtering must happen before LIMIT, even when the excluded
    # automatic record is the newest row.
    bounded_context = store.find_for_context(
        root=str(root),  coordination_id=coordination_id, limit=1
    )
    assert [record.record_id for record in bounded_context] == [manual_active.record_id]

    # Management lookups still expose the stored record; filtering does not
    # delete or rewrite legacy data.
    assert store.get(
        legacy_automatic.record_id,
        scope=AgentScope.REPOSITORY,
        root=str(root),
        repository_id=coordination_id,
    ) == records[0]
    assert store.find(
        scope=AgentScope.REPOSITORY,
        record_id=legacy_automatic.record_id,
        root=str(root),
        repository_id=coordination_id,

        semantic=False,
    ) == [records[0]]
