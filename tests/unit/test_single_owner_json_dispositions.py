from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from tools.single_owner_json_dispositions import (
    DispositionError,
    load_dispositions,
    require_all_dispositions_used,
    transform_json,
)


def _source_pin():
    return hashlib.sha256(b"source snapshot").hexdigest()


def _checkpoint(state_data):
    return {"phase": "active", "next_action": "continue", "affected_paths": [],
            "evidence_ids": [], "blockers": [], "state_data": state_data}


def _manifest(tmp_path, record, operations, *, store="agent_state", table="agent_memory_records", column="provenance", source_sha=None):
    raw = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    body = {
        "version": 1,
        "source_sha256": source_sha or _source_pin(),
        "entries": [
            {
                "store": store,
                "table": table,
                "column": column,
                "key": "record-1",
                "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "operations": operations,
            }
        ],
    }
    path = tmp_path / "dispositions.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path, raw


def test_exact_pinned_pointer_removal_preserves_opaque_payload(tmp_path):
    source = _source_pin()
    record = {"tenant_key": "retired", "content": "tenant_key is meaningful prose"}
    path, raw = _manifest(tmp_path, record, [{"op": "remove_json_pointer", "pointer": "/tenant_key"}])
    manifest = load_dispositions(path, source_sha256=source)
    with pytest.raises(FrozenInstanceError):
        manifest.source_sha256 = "0" * 64

    converted, proof = transform_json(raw, store="agent_state", table="agent_memory_records", column="provenance", key="record-1", manifest=manifest)
    assert json.loads(converted) == {"content": record["content"]}
    assert proof["removed_values"] == ({"pointer": "/tenant_key", "value": "retired"},)
    require_all_dispositions_used(manifest, [proof])


def test_missing_selector_does_not_transform_and_unused_manifest_rejects(tmp_path):
    record = {"tenant_scope": "keep"}
    path, raw = _manifest(tmp_path, record, [{"op": "remove_json_pointer", "pointer": "/tenant_scope"}])
    manifest = load_dispositions(path, source_sha256=_source_pin())

    unchanged, proof = transform_json(raw, store="agent_state", table="agent_memory_records", column="value", key="record-1", manifest=manifest)
    assert unchanged == raw
    assert proof["matched"] is False
    with pytest.raises(DispositionError, match="unused"):
        require_all_dispositions_used(manifest, [proof])


def test_manifest_pin_and_opaque_paths_fail_closed(tmp_path):
    record = {"tenant_id": "domain data"}
    path, _ = _manifest(tmp_path, record, [{"op": "remove_json_pointer", "pointer": "/metadata/tenant_id"}])
    with pytest.raises(DispositionError, match="not registered"):
        load_dispositions(path, source_sha256=_source_pin())

    path, _ = _manifest(tmp_path, record, [{"op": "remove_json_pointer", "pointer": "/identity"}])
    with pytest.raises(DispositionError, match="not registered"):
        load_dispositions(path, source_sha256=_source_pin())

    path, _ = _manifest(tmp_path, record, [{"op": "remove_json_pointer", "pointer": "/tenant_id"}])
    with pytest.raises(DispositionError, match="pin mismatch"):
        load_dispositions(path, source_sha256="0" * 64)


@pytest.mark.parametrize("folder_name", ["repo", "repo with spaces"])
def test_task_scope_v1_conversion_keeps_root_and_other_fields(tmp_path, folder_name):
    directory = tmp_path / folder_name
    directory.mkdir()
    root = str(directory.resolve())
    old_scope = {"version": 1, "repo_root": root, "tenant_id": "retired"}
    record = _checkpoint({"_agent_task_scope": old_scope,
                          "goal_contract": {"metadata": {"tenant_id": "opaque task content"}}})
    path, raw = _manifest(
        tmp_path,
        record,
        [{"op": "upgrade_task_scope", "pointer": "/state_data/_agent_task_scope", "expected_old": old_scope, "repo_root": root}],
        table="agent_tasks_projection",
        column="checkpoint",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())

    converted, proof = transform_json(raw, store="agent_state", table="agent_tasks_projection", column="checkpoint", key="record-1", manifest=manifest)
    result = json.loads(converted)
    assert result["state_data"]["_agent_task_scope"] == {"version": 2, "repo_root": root}
    assert result["state_data"]["goal_contract"]["metadata"]["tenant_id"] == "opaque task content"
    assert proof["removed_values"] == ({"pointer": "/state_data/_agent_task_scope/tenant_id", "value": "retired"},)


def test_memory_context_v1_upgrade_requires_explicit_actual_context_and_preserves_items(tmp_path):
    directory = tmp_path / "repo with spaces"
    directory.mkdir()
    root = str(directory.resolve())
    old_scope = {"version": 1, "repo_root": root, "tenant_id": "retired"}
    old_memory = {
        "schema_version": 1, "tenant_key": "retired", "instruction": "keep this instruction",
        "items": [{"memory_id": "m-1", "text": "preserve full item"}],
        "warnings": [], "estimated_tokens": 17,
    }
    record = {
        "phase": "active", "next_action": "continue", "affected_paths": [], "evidence_ids": [],
        "blockers": [], "state_data": {"_agent_task_scope": old_scope, "memory_context": old_memory},
    }
    context = {"root": root, "coordination_id": "coord-1", "task_id": "record-1",
               "session_id": "session-1", "clone_id": "", "worktree_id": "", "branch": "main"}
    path, raw = _manifest(
        tmp_path, record,
        [{"op": "upgrade_task_scope", "pointer": "/state_data/_agent_task_scope",
          "expected_old": old_scope, "repo_root": root},
         {"op": "upgrade_memory_context_v2", "pointer": "/state_data/memory_context",
          "expected_old": old_memory, "context": context}],
        table="agent_tasks_projection", column="checkpoint",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())
    converted, _proof = transform_json(raw, store="agent_state", table="agent_tasks_projection",
                                        column="checkpoint", key="record-1", manifest=manifest)
    result = json.loads(converted)
    migrated = result["state_data"]["memory_context"]
    assert migrated == {key: value for key, value in old_memory.items() if key != "tenant_key"} | {
        "schema_version": 2, "context": context}
    assert migrated["items"] == old_memory["items"]
    assert "tenant_key" not in migrated


def test_memory_context_upgrade_without_full_context_is_rejected(tmp_path):
    root = str(tmp_path.resolve())
    old = {"schema_version": 1, "instruction": "i", "items": [], "warnings": [], "estimated_tokens": 0}
    record = _checkpoint({"memory_context": old})
    path, _raw = _manifest(
        tmp_path, record,
        [{"op": "upgrade_memory_context_v2", "pointer": "/state_data/memory_context",
          "expected_old": old, "context": {"root": root}}],
        table="agent_tasks_projection", column="checkpoint",
    )
    with pytest.raises(DispositionError, match="exact canonical identity"):
        load_dispositions(path, source_sha256=_source_pin())


def test_memory_context_archive_preserves_typed_snapshot_and_reason(tmp_path):
    memory = {"schema_version": 1, "tenant_key": "retired", "instruction": "full instruction",
              "items": [{"memory_id": "m-1", "content": {"count": 3, "enabled": False}}],
              "warnings": [{"code": "warning", "detail": "preserve"}], "estimated_tokens": 23}
    record = {"phase": "active", "next_action": "continue", "affected_paths": [], "evidence_ids": [],
              "blockers": [], "state_data": {"memory_context": memory}}
    reason = "legacy context has no source-backed coordination identifier"
    path, raw = _manifest(
        tmp_path, record,
        [{"op": "archive_memory_context", "pointer": "/state_data/memory_context",
          "expected_old": memory, "reason": reason}],
        table="agent_tasks_projection", column="checkpoint",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())
    converted, proof = transform_json(raw, store="agent_state", table="agent_tasks_projection",
                                      column="checkpoint", key="record-1", manifest=manifest)
    assert "memory_context" not in json.loads(converted)["state_data"]
    assert proof["archive_reason"] == reason
    assert proof["removed_values"] == ({"pointer": "/state_data/memory_context", "value": memory},)


def test_memory_context_archive_rejects_empty_reason_and_changed_old_record(tmp_path):
    memory = {"schema_version": 1, "instruction": "i", "items": [], "warnings": [], "estimated_tokens": 0}
    record = {"phase": "active", "next_action": "continue", "affected_paths": [], "evidence_ids": [],
              "blockers": [], "state_data": {"memory_context": memory}}
    operation = {"op": "archive_memory_context", "pointer": "/state_data/memory_context",
                 "expected_old": memory, "reason": " "}
    path, _raw = _manifest(tmp_path, record, [operation], table="agent_tasks_projection", column="checkpoint")
    with pytest.raises(DispositionError, match="archive reason"):
        load_dispositions(path, source_sha256=_source_pin())

    operation["reason"] = "explicit archive"
    operation["expected_old"] = {**memory, "instruction": "different but valid old pin"}
    path, raw = _manifest(tmp_path, record, [operation], table="agent_tasks_projection", column="checkpoint")
    manifest = load_dispositions(path, source_sha256=_source_pin())
    with pytest.raises(DispositionError, match="exact pinned v1 archive"):
        transform_json(raw, store="agent_state", table="agent_tasks_projection", column="checkpoint",
                       key="record-1", manifest=manifest)


def test_task_scope_upgrade_preserves_missing_historical_root_without_rebinding(tmp_path):
    historical_root = str((tmp_path / "deleted-repository").resolve())
    assert not Path(historical_root).exists()
    old_scope = {"version": 1, "repo_root": historical_root, "tenant_id": "retired"}
    record = _checkpoint({"_agent_task_scope": old_scope})
    path, raw = _manifest(
        tmp_path,
        record,
        [{"op": "upgrade_task_scope", "pointer": "/state_data/_agent_task_scope",
          "expected_old": old_scope, "repo_root": historical_root}],
        table="agent_tasks_projection",
        column="checkpoint",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())
    converted, proof = transform_json(raw, store="agent_state", table="agent_tasks_projection",
                                       column="checkpoint", key="record-1", manifest=manifest)
    assert json.loads(converted)["state_data"]["_agent_task_scope"] == {
        "version": 2, "repo_root": historical_root}
    assert proof["removed_values"] == ({
        "pointer": "/state_data/_agent_task_scope/tenant_id", "value": "retired"},)


def test_duplicate_operations_and_nonmatching_old_scope_reject(tmp_path):
    record = {"tenant": "retired"}
    operation = {"op": "remove_json_pointer", "pointer": "/tenant"}
    path, _ = _manifest(tmp_path, record, [operation, operation])
    with pytest.raises(DispositionError, match="duplicate"):
        load_dispositions(path, source_sha256=_source_pin())

    root = str(tmp_path.resolve())
    old_scope = {"version": 1, "repo_root": root}
    record = _checkpoint({"_agent_task_scope": {"version": 1, "repo_root": root, "tenant_id": "different"}})
    path, raw = _manifest(
        tmp_path,
        record,
        [{"op": "upgrade_task_scope", "pointer": "/state_data/_agent_task_scope", "expected_old": old_scope, "repo_root": root}],
        table="agent_tasks_projection",
        column="checkpoint",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())
    with pytest.raises(DispositionError, match="exact pinned old object"):
        transform_json(raw, store="agent_state", table="agent_tasks_projection", column="checkpoint", key="record-1", manifest=manifest)


def test_snapshot_state_scope_uses_only_registered_checkpoint_path(tmp_path):
    root = str(tmp_path.resolve())
    old_scope = {"version": 1, "repo_root": root}
    record = {
        "task_id": "task-1",
        "status": "active",
        "owner": "agent-1",
        "lease_id": "lease-1",
        "contract": {
            "goal": "goal",
            "description": "",
            "acceptance_criteria": [],
            "scope": "task",
            "non_goals": [],
            "constraints": [],
            "risk_profile": "normal",
            "slo_profile": {},
        },
        "context": {"repository_id": "repo", "clone_id": "", "worktree_id": "", "branch": "", "task_id": "task-1", "session_id": ""},
        "checkpoint": {
            "phase": "",
            "next_action": "",
            "affected_paths": [],
            "evidence_ids": [],
            "blockers": [],
            "state_data": {"_agent_task_scope": old_scope},
        },
        "verification_receipts": {},
        "created_at": 1.0,
        "updated_at": 1.0,
        "heartbeat_expires_at": 0.0,
        "stale": False,
        "stale_reason": "",
    }
    path, raw = _manifest(
        tmp_path,
        record,
        [{"op": "upgrade_task_scope", "pointer": "/checkpoint/state_data/_agent_task_scope", "expected_old": old_scope, "repo_root": root}],
        table="agent_snapshots",
        column="state",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())
    converted, proof = transform_json(raw, store="agent_state", table="agent_snapshots", column="state", key="record-1", manifest=manifest)
    assert json.loads(converted)["checkpoint"]["state_data"]["_agent_task_scope"] == {"version": 2, "repo_root": root}
    assert proof["removed_count"] == 0


def test_domain_snapshot_with_checkpoint_looking_object_is_rejected_untouched(tmp_path):
    root = str(tmp_path.resolve())
    old_scope = {"version": 1, "repo_root": root}
    record = {"domain": "opaque", "checkpoint": {"state_data": {"_agent_task_scope": old_scope}}}
    path, raw = _manifest(
        tmp_path,
        record,
        [{"op": "upgrade_task_scope", "pointer": "/checkpoint/state_data/_agent_task_scope", "expected_old": old_scope, "repo_root": root}],
        table="agent_snapshots",
        column="state",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())
    with pytest.raises(DispositionError, match="serialized TaskState envelope"):
        transform_json(raw, store="agent_state", table="agent_snapshots", column="state", key="record-1", manifest=manifest)
    assert raw == json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    assert json.loads(raw)["checkpoint"]["state_data"]["_agent_task_scope"] == old_scope


def test_scope_context_removal_preserves_exact_six_fields(tmp_path):
    record = {
        "repository_id": "repo",
        "clone_id": "clone",
        "worktree_id": "worktree",
        "branch": "main",
        "task_id": "task-7",
        "session_id": "session-2",
        "tenant_key": "retired",
    }
    path, raw = _manifest(
        tmp_path,
        record,
        [{"op": "remove_json_pointer", "pointer": "/tenant_key"}],
        table="agent_tasks_projection",
        column="context",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())
    converted, proof = transform_json(raw, store="agent_state", table="agent_tasks_projection", column="context", key="record-1", manifest=manifest)
    assert json.loads(converted) == {key: record[key] for key in record if key != "tenant_key"}
    assert "schema_version" not in json.loads(converted)
    assert proof["removed_values"] == ({"pointer": "/tenant_key", "value": "retired"},)


@pytest.mark.parametrize(
    ("store", "table", "column", "pointer"),
    [
        ("work_orchestrator", "work_orders", "payload_json", "/tenant"),
        ("async_jobs", "async_jobs", "payload_json", "/tenant_key"),
    ],
)
def test_job_submission_payload_control_removals_are_root_only(tmp_path, store, table, column, pointer):
    name = pointer[1:]
    record = {name: "retired", "task": "tenant text remains", "prompt": "tenant_key is opaque"}
    path, raw = _manifest(tmp_path, record, [{"op": "remove_json_pointer", "pointer": pointer}], store=store, table=table, column=column)
    manifest = load_dispositions(path, source_sha256=_source_pin())
    converted, _ = transform_json(raw, store=store, table=table, column=column, key="record-1", manifest=manifest)
    result = json.loads(converted)
    assert name not in result
    assert result["task"] == record["task"]
    assert result["prompt"] == record["prompt"]


def test_work_order_tenant_disposition_rejects_nested_domain_pointer(tmp_path):
    record = {"metadata": {"tenant": "opaque domain value"}}
    path, _ = _manifest(
        tmp_path,
        record,
        [{"op": "remove_json_pointer", "pointer": "/metadata/tenant"}],
        store="work_orchestrator",
        table="work_orders",
        column="payload_json",
    )
    with pytest.raises(DispositionError, match="not registered"):
        load_dispositions(path, source_sha256=_source_pin())


def test_telemetry_conversion_allows_only_explicit_direct_guard_container_path(tmp_path):
    record = {"metadata": {"tenant_scope": "retired", "content": "opaque"}, "payload": "tenant text"}
    path, raw = _manifest(
        tmp_path,
        record,
        [{"op": "remove_json_pointer", "pointer": "/metadata/tenant_scope"}],
        store="telemetry",
        table="snapshots",
        column="metrics_json",
    )
    manifest = load_dispositions(path, source_sha256=_source_pin())
    converted, _ = transform_json(raw, store="telemetry", table="snapshots", column="metrics_json", key="record-1", manifest=manifest)
    result = json.loads(converted)
    assert result == {"metadata": {"content": "opaque"}, "payload": "tenant text"}

    path, _ = _manifest(
        tmp_path,
        record,
        [{"op": "remove_json_pointer", "pointer": "/metadata/nested/tenant_scope"}],
        store="telemetry",
        table="snapshots",
        column="metrics_json",
    )
    with pytest.raises(DispositionError, match="not registered"):
        load_dispositions(path, source_sha256=_source_pin())


def test_async_result_json_has_no_domain_payload_disposition(tmp_path):
    record = {"answer": {"tenant": "meaningful domain content"}}
    path, raw = _manifest(
        tmp_path,
        record,
        [{"op": "remove_json_pointer", "pointer": "/tenant"}],
        store="async_jobs",
        table="async_jobs",
        column="result_json",
    )
    with pytest.raises(DispositionError, match="not registered"):
        load_dispositions(path, source_sha256=_source_pin())


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_json_numbers_reject_but_opaque_strings_remain_text(tmp_path, number):
    raw = f'{{"tenant_key":"retired","value":{number}}}'
    source = _source_pin()
    body = {
        "version": 1,
        "source_sha256": source,
        "entries": [
            {
                "store": "agent_state",
                "table": "agent_memory_records",
                "column": "provenance",
                "key": "record-1",
                "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "operations": [{"op": "remove_json_pointer", "pointer": "/tenant_key"}],
            }
        ],
    }
    path = tmp_path / "nonfinite.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    manifest = load_dispositions(path, source_sha256=source)
    with pytest.raises(DispositionError, match="non-finite"):
        transform_json(raw, store="agent_state", table="agent_memory_records", column="provenance", key="record-1", manifest=manifest)

    record = {"tenant_key": "retired", "content": "NaN Infinity -Infinity are plain text"}
    path, raw_text = _manifest(tmp_path, record, [{"op": "remove_json_pointer", "pointer": "/tenant_key"}])
    manifest = load_dispositions(path, source_sha256=source)
    converted, _ = transform_json(raw_text, store="agent_state", table="agent_memory_records", column="provenance", key="record-1", manifest=manifest)
    assert json.loads(converted)["content"] == record["content"]


@pytest.mark.parametrize("store", [" agent_state", "agent_state ", "agent\x00state"])
def test_identity_strings_with_outer_whitespace_or_nul_reject(tmp_path, store):
    path, _ = _manifest(tmp_path, {"tenant": "old"}, [{"op": "remove_json_pointer", "pointer": "/tenant"}])
    body = json.loads(path.read_text(encoding="utf-8"))
    body["entries"][0]["store"] = store
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(DispositionError, match="store must be"):
        load_dispositions(path, source_sha256=_source_pin())
