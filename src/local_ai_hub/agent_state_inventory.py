"""Offline schema-only inventory for the existing Agent OS database.

Classification is a migration prerequisite, never permission to export.
Mixed JSON columns still require explicit field-level projection and review.
This command does not instantiate stores, read row values, or perform cutover.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

# Physical SQL fields from the existing schema initializers. G+L denotes a
# future portable subset, C a curated subset, L private/local, and R a
# rebuildable local index. Even a G+L field is NOT export authorization.
_SCHEMA: dict[str, tuple[str, str, dict[str, str]]] = {}


def _classify(table: str, owner: str, consumers: str, **groups: str) -> None:
    fields: dict[str, str] = {}
    for category, names in groups.items():
        for name in names.split():
            if name in fields:
                raise RuntimeError("Duplicate storage field classification")
            fields[name] = {"portable": "G+L", "curated": "C", "local": "L", "derived": "R"}[category]
    _SCHEMA[table] = (owner, consumers, fields)


_classify("agent_events", "agent_events.py:AgentStateStore", "TaskStore, MemoryStore, VerificationStore, event delta, recovery",
          local="stream_id seq event_id kind payload idempotency_key correlation_id actor created_at")
_classify("agent_snapshots", "agent_events.py:AgentStateStore", "event replay and recovery",
          local="snapshot_id stream_id seq state created_at")
_classify("agent_event_cursors", "agent_events.py:AgentStateStore", "event append/replay",
          local="stream_id last_seq first_retained_seq")
_classify("agent_tasks_projection", "agent_task_questions.py:TaskQuestionMixin; agent_task_plan.py:TaskPlanSyncMixin",
          "TaskStore create/get/list/transition/checkpoint; VerificationStore; HTTP/MCP",
          portable="task_id status contract checkpoint", curated="context owner created_at updated_at",
          local="lease_id receipts heartbeat_expires_at")
_classify("agent_task_search_documents", "agent_task_core.py:TaskCoreMixin", "TaskStore search",
          derived="task_id fields")
_classify("agent_task_search_grams", "agent_task_core.py:TaskCoreMixin", "TaskStore search",
          derived="task_id gram")
_classify("agent_task_search_index_state", "agent_task_core.py:TaskCoreMixin", "TaskStore search backfill",
          derived="task_id source_digest fields_digest grams_digest grams_count")
_classify("agent_questions", "agent_task_questions.py:TaskQuestionMixin", "TaskStore ask/answer; task HTTP/MCP",
          portable="question_id task_id status", curated="question answer asked_by answered_by created_at answered_at",
          local="root session_id")
_classify("agent_memory_records", "agent_memory.py:MemoryStore", "ContextCompiler; TaskStore memory adoption; memory HTTP/MCP",
          portable="record_id kind scope key status contradicts_record_id supersedes_record_id expires_at",
          curated="scope_id value confidence source sensitivity quarantine_reason provenance created_at updated_at",
          local="evidence_ids")
_classify("agent_entity_relations", "agent_memory.py:MemoryStore", "context graph traversal and memory relation queries",
          portable="relation_id source_entity relation target_entity", curated="weight metadata created_at updated_at",
          local="repository_id")
_classify("agent_memory_fts", "agent_memory.py:MemoryStore", "memory retrieval",
          derived="record_id key value agent_memory_fts rank")
_classify("agent_memory_embeddings", "agent_memory.py:MemoryStore", "semantic memory retrieval",
          derived="record_id embedding created_at embedding_space_id model_name dimension")
_classify("agent_incidents", "agent_incidents.py:IncidentStore", "CommandBroker; ContextCompiler; incident HTTP",
          portable="incident_id operation_class error_class signature_hash resolved ignored expires_at",
          curated="redacted_message root_cause verified_fix confidence affected_paths created_at updated_at",
          local="state_revision attempts evidence_ids repository_key")
_classify("agent_verification_receipts", "agent_verification.py:VerificationStore", "completion gates; CommandBroker; verification HTTP",
          curated="criterion passed observed_at expires_at repository_revision details",
          local="receipt_id task_id change_intent_id evidence_id command_id")
_classify("agent_verification_task_outbox", "agent_verification.py:VerificationStore", "receipt/task transaction reconciliation",
          local="receipt_id task_id criterion status created_at completed_at")
_classify("agent_change_intents", "agent_verification.py:VerificationStore", "command and verification lifecycle",
          portable="change_id task_id", curated="affected_paths affected_symbols expected_impact rollback_description created_at")
_classify("agent_outcomes", "agent_verification.py:VerificationStore", "verification outcome lifecycle",
          portable="outcome_id change_id task_id kind", curated="actor details created_at")
_classify("agent_blackboard", "agent_blackboard.py:BlackboardStore", "ContextCompiler; swarm; board HTTP/MCP",
          curated="board_id section content author", local="vector_clock timestamp version")
_classify("agent_budgets", "agent_policy.py:PolicyEngine", "TaskStore and command policy",
          curated="task_id max_tokens max_compute_seconds max_external_calls",
          local="used_tokens used_compute_seconds used_external_calls updated_at")
_classify("agent_external_call_reservations", "agent_policy.py:PolicyEngine", "external call admission",
          local="invocation_id task_id reserved_at")
_classify("agent_learning_candidates", "agent_learning.py:LearningStore", "learning policy and operator review",
          curated="candidate_id name baseline_version candidate_version status slo_thresholds metrics approver created_at updated_at")
_classify("agent_swarms", "swarm.py:SwarmCoordinator", "swarm lifecycle, leases, blackboard, verification",
          curated="swarm_id goal target_paths test_command author history",
          local="root state receipt_id created_at updated_at version")

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_MAX_TABLES = 256
_MAX_FIELDS = 128


def _sidecars_absent(db: Path) -> bool:
    for suffix in ("-wal", "-journal", "-shm"):
        sidecar = db.with_name(db.name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            return False
    return True


def _identity(db: Path) -> tuple[int, int, int, int, int]:
    info = db.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def inspect_agent_state_inventory(state_dir: Path | str) -> dict[str, Any]:
    """Inspect an offline SQLite schema only, without writing even a WAL/SHM.

    Caller must stop the Hub or use a clean offline backup. Refuse sidecars
    rather than using immutable SQLite to silently ignore pending WAL data.
    """
    def blocked(reason: str) -> dict[str, Any]:
        return {"success": False, "complete": False, "reason": reason,
                "tables": [], "canonical_cutover_supported": False, "row_values_read": False}

    try:
        directory = Path(state_dir).resolve(strict=True)
        db = directory / "agent_state.sqlite"
        if db.is_symlink() or getattr(db, "is_junction", lambda: False)() or not db.is_file():
            return blocked("database_unavailable")
        if not _sidecars_absent(db):
            return blocked("offline_snapshot_required")
        before = _identity(db)
        rows: list[dict[str, Any]] = []
        complete = True
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1.0)) as con:
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            tables = con.execute("PRAGMA main.table_list").fetchmany(_MAX_TABLES + 1)
            if len(tables) > _MAX_TABLES:
                complete = False
            for schema, name, kind, *_ in sorted(tables[:_MAX_TABLES], key=lambda row: row[1]):
                if schema != "main" or name in {"sqlite_schema", "sqlite_sequence"}:
                    continue
                if not isinstance(name, str) or not _NAME.fullmatch(name):
                    complete = False
                    rows.append({"table": "<unsupported-name>", "state": "unclassified"})
                    continue
                if kind == "shadow" and name in {
                    "agent_memory_fts_data", "agent_memory_fts_idx", "agent_memory_fts_content",
                    "agent_memory_fts_docsize", "agent_memory_fts_config",
                }:
                    rows.append({"table": name, "state": "classified", "owner": "agent_memory.py:MemoryStore",
                                 "classification": "R", "consumer": "FTS5 derived index"})
                    continue
                definition = _SCHEMA.get(name)
                if definition is None or kind not in {"table", "virtual"}:
                    complete = False
                    rows.append({"table": name, "state": "unclassified"})
                    continue
                owner, consumers, fields = definition
                columns = con.execute("SELECT name FROM pragma_table_xinfo(?)", (name,)).fetchmany(_MAX_FIELDS + 1)
                observed = []
                table_complete = len(columns) <= _MAX_FIELDS
                for (column,) in columns[:_MAX_FIELDS]:
                    if not isinstance(column, str) or not _NAME.fullmatch(column):
                        column = "<unsupported-name>"
                    category = fields.get(column, "unclassified")
                    if category == "unclassified":
                        table_complete = False
                    observed.append({"field": column, "classification": category})
                missing = sorted(set(fields) - {row["field"] for row in observed})
                if missing:
                    table_complete = False
                complete = complete and table_complete
                rows.append({"table": name, "state": "classified" if table_complete else "unclassified",
                             "owner": owner, "consumers": consumers, "fields": observed, "missing_fields": missing})
        if _identity(db) != before or not _sidecars_absent(db) or db.is_symlink():
            return blocked("database_changed_during_inventory")
        if not rows:
            return blocked("schema_unavailable")
        return {
            "success": True, "complete": complete, "tables": rows,
            "scope": "agent_state.sqlite_schema_only", "canonical_cutover_supported": False,
            "row_values_read": False, "classification_is_export_authority": False,
            "mixed_json_fields_require_projection_review": True,
            "unobserved_known_tables": sorted(set(_SCHEMA) - {row["table"] for row in rows}),
            "remaining_inventory": "other databases, file stores, JSON subfields, all consumers and migration tests",
        }
    except (OSError, ValueError, sqlite3.Error, RuntimeError):
        return blocked("schema_unavailable")
