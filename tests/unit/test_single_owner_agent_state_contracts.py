from __future__ import annotations

from tools.single_owner_agent_state_contracts import (
    AGENT_STATE_STORE_DDL,
    JSON_TRANSFORMS_REQUIRED,
    RETIRED_COLUMNS,
    ROW_TRANSFORMS_REQUIRED,
    STANDALONE_STORE_DDL,
    UNSUPPORTED_STORE_METADATA,
)


def test_supported_standalone_contracts_are_ownerless_and_source_literal() -> None:
    swarm_tables, swarm_indexes = STANDALONE_STORE_DDL["swarm"]
    assert set(swarm_tables) == {"agent_swarms"}
    assert "swarm_id TEXT PRIMARY KEY" in swarm_tables["agent_swarms"]
    assert "root TEXT NOT NULL" in swarm_tables["agent_swarms"]
    assert "tenant" not in swarm_tables["agent_swarms"]
    assert swarm_indexes == ()

    lease_tables, lease_indexes = STANDALONE_STORE_DDL["leases"]
    assert set(lease_tables) == {"leases", "lease_waits"}
    assert "owner TEXT NOT NULL" in lease_tables["leases"]
    assert "root_id TEXT NOT NULL" in lease_tables["leases"]
    assert "owner TEXT NOT NULL" in lease_tables["lease_waits"]
    assert all("tenant" not in sql for sql in lease_tables.values())
    assert len(lease_indexes) == 3
    assert all("tenant" not in sql for sql in lease_indexes)


def test_incomplete_agent_state_is_never_convertible_but_fence_ddl_is_literal() -> None:
    assert AGENT_STATE_STORE_DDL == {}
    assert UNSUPPORTED_STORE_METADATA["agent_state"]["supported"] is False
    assert "agent_events" in UNSUPPORTED_STORE_METADATA["agent_state"]["required_objects"]
    assert "agent_verification_receipts" in UNSUPPORTED_STORE_METADATA["agent_state"]["required_objects"]
    fence_tables, fence_indexes = STANDALONE_STORE_DDL["work_fencing"]
    assert set(fence_tables) == {
        "writer_fence_counters", "writer_fence_leases", "writer_fence_attempts"
    }
    assert "work_id TEXT NOT NULL DEFAULT ''" in fence_tables["writer_fence_leases"]
    assert len(fence_indexes) == 4


def test_retired_columns_and_identity_transforms_are_explicit() -> None:
    assert RETIRED_COLUMNS == {
        "agent_swarms": ("tenant", "tenant_identity"),
        "leases": ("tenant",),
        "lease_waits": ("tenant",),
    }
    transforms = {(item.get("table"), item.get("from_column")): item for item in ROW_TRANSFORMS_REQUIRED}
    assert transforms[("leases", "tenant")]["to_column"] == "owner"
    assert transforms[("leases", "tenant")]["reject_if_unmapped"] is True
    assert transforms[("lease_waits", "tenant")]["to_column"] == "owner"
    assert transforms[("lease_waits", "tenant")]["reject_if_unmapped"] is True
    fence_scope = next(item for item in ROW_TRANSFORMS_REQUIRED if item.get("column") == "scope_id")
    assert fence_scope["tables"] == ("writer_fence_leases", "writer_fence_attempts")
    assert fence_scope["reject_if_unmapped"] is True
    assert "resource and owner_id do not prove scope" in fence_scope["requires"]


def test_json_conversion_preserves_declared_context_without_promoting_legacy_identity() -> None:
    transforms = {(item["table"], item["column"]): item for item in JSON_TRANSFORMS_REQUIRED}
    memory = transforms[("agent_memory_records", "provenance")]
    assert "coordination_id" in memory["preserve_keys"]
    assert "root" in memory["preserve_keys"]

    task_context = transforms[("agent_tasks_projection", "context")]
    assert "required_schema_version" not in task_context
    assert task_context["preserve_keys"] == ("repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id")
    assert "session_id" in task_context["preserve_keys"]

    receipt_details = transforms[("agent_verification_receipts", "details")]
    assert receipt_details["forbid_promotions"] == (
        "legacy receipt freshness claims",
        "legacy task-root provenance",
    )
