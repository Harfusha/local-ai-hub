"""Source-literal schema contracts for the offline single-owner converter.

This module deliberately has no project imports. A store is convertible only
when its complete schema and row transforms are represented here; unsupported
stores fail closed instead of being accepted from a partial schema sample.
"""

from __future__ import annotations

from typing import Final

StoreDDL = tuple[dict[str, str], tuple[str, ...]]


# Exact current CREATE statements from SwarmCoordinator, ScopeLeaseStore, and
# the source-literal writer-fence contract.
STANDALONE_STORE_DDL: Final[dict[str, StoreDDL]] = {
    "swarm": (
        {
            "agent_swarms": """CREATE TABLE IF NOT EXISTS agent_swarms (
                        swarm_id TEXT PRIMARY KEY,
                        goal TEXT NOT NULL,
                        target_paths TEXT NOT NULL,
                        test_command TEXT NOT NULL,
                        author TEXT NOT NULL,
                        root TEXT NOT NULL,
                        state TEXT NOT NULL,
                        receipt_id TEXT,
                        history TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        version INTEGER NOT NULL
                    )""",
        },
        (),
    ),
    "leases": (
        {
            "leases": """CREATE TABLE IF NOT EXISTS leases (
                                lease_id TEXT NOT NULL,
                                owner TEXT NOT NULL,
                                root_id TEXT NOT NULL,
                                root_path TEXT NOT NULL,
                                path TEXT NOT NULL,
                                purpose TEXT NOT NULL,
                                created_at REAL NOT NULL,
                                expires_at REAL NOT NULL,
                                PRIMARY KEY(lease_id, path)
                            )""",
            "lease_waits": """CREATE TABLE IF NOT EXISTS lease_waits (
                                owner TEXT NOT NULL,
                                blocked_by TEXT NOT NULL,
                                root_id TEXT NOT NULL,
                                requested_path TEXT NOT NULL,
                                updated_at REAL NOT NULL,
                                PRIMARY KEY(root_id, owner, blocked_by, requested_path)
                            )""",
        },
        (
            "CREATE INDEX IF NOT EXISTS idx_leases_root ON leases(root_id, expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_lease_waits_owner ON lease_waits(owner)",
            "CREATE INDEX IF NOT EXISTS idx_lease_waits_blocked ON lease_waits(blocked_by)",
        ),
    ),
    "work_fencing": (
        {
            "writer_fence_counters": """CREATE TABLE IF NOT EXISTS writer_fence_counters (
        resource TEXT PRIMARY KEY,
        last_token INTEGER NOT NULL CHECK(last_token >= 0)
    )""",
            "writer_fence_leases": """CREATE TABLE IF NOT EXISTS writer_fence_leases (
        lease_id TEXT PRIMARY KEY,
        resource TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
        expires_at REAL NOT NULL,
        paths_json TEXT NOT NULL,
        attempt_id TEXT NOT NULL DEFAULT '',
        attempt_token INTEGER NOT NULL DEFAULT 0,
        scope_id TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL CHECK(active IN (0, 1)),
        work_id TEXT NOT NULL DEFAULT ''
    )""",
            "writer_fence_attempts": """CREATE TABLE IF NOT EXISTS writer_fence_attempts (
        attempt_id TEXT PRIMARY KEY,
        resource TEXT NOT NULL,
        scope_id TEXT NOT NULL DEFAULT '',
        work_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
        expires_at REAL NOT NULL,
        active INTEGER NOT NULL CHECK(active IN (0, 1)),
        UNIQUE(resource, work_id, fencing_token)
    )""",
        },
        (
            "CREATE INDEX IF NOT EXISTS idx_writer_attempt_scope ON writer_fence_attempts(scope_id, work_id, active, expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_writer_fence_scope_live ON writer_fence_leases(scope_id, active, expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_writer_attempt_current ON writer_fence_attempts(resource, work_id, active, expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_writer_fence_live ON writer_fence_leases(resource, active, expires_at)",
        ),
    ),
}


# agent_state is a shared database assembled by several stores. Its full
# source-exact schema is not registered, so consumers must reject conversion.
AGENT_STATE_STORE_DDL: Final[dict[str, StoreDDL]] = {}
UNSUPPORTED_STORE_METADATA: Final[dict[str, dict[str, object]]] = {
    "agent_state": {
        "supported": False,
        "reason": "full source-exact DDL is not registered for every agent_state object",
        "required_objects": (
            "agent_events",
            "agent_snapshots",
            "agent_event_cursors",
            "agent_questions",
            "agent_tasks_projection",
            "agent_task_search_documents",
            "agent_task_search_grams",
            "agent_memory_records",
            "agent_memory_embeddings",
            "agent_memory_fts",
            "agent_entity_relations",
            "agent_verification_receipts",
            "agent_verification_task_outbox",
            "agent_change_intents",
            "agent_outcomes",
            "agent_blackboard",
            "agent_budgets",
            "agent_incidents",
            "agent_knowledge_links",
            "agent_learning_candidates",
            "agent_state_migrations",
            "agent_state_schema_versions",
            "leases",
            "lease_waits",
            "agent_swarms",
            "idx_agent_questions_session",
            "idx_lease_waits_owner",
            "idx_leases_root",
            "idx_lease_waits_blocked",
            "idx_agent_budgets_task",
            "idx_agent_change_task",
            "idx_agent_events_created",
            "idx_agent_events_kind",
            "idx_agent_incidents_fp",
            "idx_agent_incidents_lookup",
            "idx_agent_incidents_recent",
            "idx_agent_incidents_scope",
            "idx_agent_klinks_path",
            "idx_agent_memory_expires",
            "idx_agent_memory_provenance_branch",
            "idx_agent_memory_provenance_clone_id",
            "idx_agent_memory_provenance_repository",
            "idx_agent_memory_provenance_root",
            "idx_agent_memory_provenance_worktree_id",
            "idx_agent_memory_scope_identity",
            "idx_agent_memory_scope_key",
            "idx_agent_memory_updated",
            "idx_agent_outcomes_change",
            "idx_agent_outcomes_task",
            "idx_agent_snapshots_stream",
            "idx_agent_tasks_status",
            "idx_agent_tasks_status_updated",
            "idx_agent_tasks_updated",
            "idx_agent_verif_task",
            "idx_agent_verif_task_observed",
            "idx_agent_verif_task_outbox_pending",
            "idx_blackboard_board",
            "idx_entity_rel_source",
            "idx_entity_rel_target",
            "idx_entity_rel_type",
            "idx_agent_task_search_grams_gram",
        ),
    },
}


# Only columns verified as removed by the current source contracts/fixtures.
# "tenant_identity" is present in the legacy swarm contract; the remaining
# columns are the legacy lease-store tenant partition columns.
RETIRED_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "agent_swarms": ("tenant", "tenant_identity"),
    "leases": ("tenant",),
    "lease_waits": ("tenant",),
}


# Explicit row transforms required before conversion. These are requirements,
# not implicit transforms: the converter must stop when identity is ambiguous.
ROW_TRANSFORMS_REQUIRED: Final[tuple[dict[str, object], ...]] = (
    {
        "table": "leases",
        "from_column": "tenant",
        "to_column": "owner",
        "requires": "explicit actual-writer mapping for every row; retain root_id, root_path, path, purpose, and expiry",
        "reject_if_unmapped": True,
    },
    {
        "table": "lease_waits",
        "from_column": "tenant",
        "to_column": "owner",
        "requires": "explicit actual-writer mapping for every row; retain root_id, blocked_by, requested_path, and timestamp",
        "reject_if_unmapped": True,
    },
    {
        "table": "agent_swarms",
        "from_columns": ("tenant", "tenant_identity"),
        "requires": "preserve swarm_id, root, task/author provenance; reject if retired fields are needed to distinguish records",
        "reject_if_ambiguous": True,
    },
    {
        "tables": ("writer_fence_leases", "writer_fence_attempts"),
        "column": "scope_id",
        "when": "empty",
        "requires": "explicit actual root/project-scope mapping for each legacy row; resource and owner_id do not prove scope",
        "reject_if_unmapped": True,
    },
)


# JSON-backed fields require explicit, collision-checked conversion. In
# particular, legacy roots or freshness cannot be guessed from retired fields.
JSON_TRANSFORMS_REQUIRED: Final[tuple[dict[str, object], ...]] = (
    {
        "table": "agent_memory_records",
        "column": "provenance",
        "retired_keys": ("tenant", "tenant_key"),
        "preserve_keys": ("root", "repository_id", "coordination_id", "task_id", "session_id", "clone_id", "worktree_id", "branch"),
        "rule": "remove retired provenance only under explicit conversion; do not substitute physical root for coordination identity",
    },
    {
        "table": "agent_tasks_projection",
        "column": "context",
        "preserve_keys": ("repository_id", "clone_id", "worktree_id", "branch", "task_id", "session_id"),
        "retired_keys": ("tenant", "tenant_key"),
        "rule": "validate direct ScopeContext fields; preserve omitted defaults and never infer repository or physical-root identity",
    },
    {
        "table": "agent_tasks_projection",
        "column": "checkpoint",
        "retired_keys": ("tenant", "tenant_key"),
        "rule": "preserve task and repository provenance; do not promote legacy root fields",
    },
    {
        "table": "agent_verification_receipts",
        "column": "details",
        "rule": "preserve explicit receipt evidence; never synthesize current freshness or success from legacy metadata",
        "forbid_promotions": ("legacy receipt freshness claims", "legacy task-root provenance"),
    },
)
