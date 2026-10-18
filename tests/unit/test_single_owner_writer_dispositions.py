"""Offline writer-disposition contract tests (authored, not executed here)."""

from __future__ import annotations

import json

import pytest

from tools.single_owner_writer_dispositions import (
    WRITER_MAP_SCHEMA,
    load_writer_map,
    transform_writer_row,
    typed_row_sha256,
    validate_target_key_uniqueness,
    validate_writer_map_usage,
)


SOURCE = "1" * 64
FACT = "2" * 64


def _manifest(tmp_path, table, row, task_id="task-a", **extra):
    extra.setdefault("task_row_sha256", FACT)
    if table == "lease_waits":
        extra.setdefault("blocked_task_row_sha256", FACT)
    document = {
        "schema": WRITER_MAP_SCHEMA,
        "source_sha256": SOURCE,
        "dispositions": [
            {
                "table": table,
                "primary_key": {
                    key: row[key]
                    for key in (
                        ("lease_id", "path")
                        if table == "leases"
                        else ("root_id", "tenant", "blocked_by", "requested_path")
                    )
                },
                "row_sha256": typed_row_sha256(table, row),
                "task_id": task_id,
                **extra,
            }
        ],
    }
    path = tmp_path / "writer-map.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return load_writer_map(path, source_sha256=SOURCE)


def _task(task_id, owner, root):
    return {
        "task_id": task_id,
        "owner": owner,
        "repo_root": str(root),
        "source_sha256": FACT,
        "task_row_sha256": FACT,
    }


def test_lease_disposition_maps_only_to_proven_task_owner(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    row = {
        "lease_id": "lease-1",
        "tenant": "retired-label",
        "root_id": "root-1",
        "root_path": str(root),
        "path": "src/file.py",
        "purpose": "edit",
        "created_at": 10.0,
        "expires_at": 20.0,
    }
    manifest = _manifest(tmp_path, "leases", row)
    task_lookup = lambda task_id: _task(task_id, "worker-17", root)
    mapped, proof = transform_writer_row(
        table="leases",
        row=row,
        manifest=manifest,
        task_lookup=task_lookup,
        root_lookup=lambda _root_id: pytest.fail("lease root comes from its exact row"),
    )
    assert mapped == {**{key: value for key, value in row.items() if key != "tenant"}, "owner": "worker-17"}
    assert proof["retired_tenant_value"] == "retired-label"
    assert proof["new_key"] == {"lease_id": "lease-1", "path": "src/file.py"}
    validate_writer_map_usage(manifest, [("leases", {"lease_id": "lease-1", "path": "src/file.py"})])
    validate_target_key_uniqueness([proof])


def test_wait_disposition_requires_same_root_blocked_task_owner(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    row = {
        "tenant": "retired-wait-label",
        "blocked_by": "old-blocker",
        "root_id": "root-1",
        "requested_path": "src/file.py",
        "updated_at": 30.0,
    }
    manifest = _manifest(tmp_path, "lease_waits", row, blocked_task_id="task-blocked")
    tasks = {
        "task-a": _task("task-a", "requester-worker", root),
        "task-blocked": _task("task-blocked", "blocking-worker", root),
    }
    mapped, proof = transform_writer_row(
        table="lease_waits",
        row=row,
        manifest=manifest,
        task_lookup=tasks.__getitem__,
        root_lookup=lambda root_id: {"root_path": str(root), "source_sha256": FACT},
    )
    assert mapped == {
        "blocked_by": "blocking-worker",
        "root_id": "root-1",
        "requested_path": "src/file.py",
        "updated_at": 30.0,
        "owner": "requester-worker",
    }
    assert proof["blocked_task"]["task_id"] == "task-blocked"
    assert proof["new_key"] == {
        "root_id": "root-1",
        "owner": "requester-worker",
        "blocked_by": "blocking-worker",
        "requested_path": "src/file.py",
    }


def test_writer_map_and_conversion_fail_closed_on_drift_or_root_mismatch(tmp_path):
    root = tmp_path / "repo"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    row = {
        "lease_id": "lease-1",
        "tenant": "retired-label",
        "root_id": "root-1",
        "root_path": str(root),
        "path": "src/file.py",
        "purpose": "edit",
        "created_at": 10.0,
        "expires_at": 20.0,
    }
    manifest = _manifest(tmp_path, "leases", row)
    changed = {**row, "purpose": "different"}
    with pytest.raises(ValueError, match="changed after the map was pinned"):
        transform_writer_row(
            table="leases", row=changed, manifest=manifest,
            task_lookup=lambda task_id: _task(task_id, "worker-17", root),
            root_lookup=lambda _root_id: None,
        )
    with pytest.raises(ValueError, match="does not exactly match"):
        transform_writer_row(
            table="leases", row=row, manifest=manifest,
            task_lookup=lambda task_id: _task(task_id, "worker-17", other),
            root_lookup=lambda _root_id: None,
        )
    with pytest.raises(ValueError, match="unused dispositions"):
        validate_writer_map_usage(manifest, [])


def test_new_target_key_collisions_reject_before_publish():
    proof = {"table": "leases", "new_key": {"lease_id": "same", "path": "x"}}
    with pytest.raises(ValueError, match="collide"):
        validate_target_key_uniqueness([proof, proof])


def test_old_owner_override_and_nonfinite_manifest_values_reject(tmp_path):
    path = tmp_path / "writer-map.json"
    path.write_text(
        '{"schema":"single_owner_writer_map.v1","source_sha256":"' + SOURCE
        + '","dispositions":[],"owner":"forced"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported fields"):
        load_writer_map(path, source_sha256=SOURCE)
    path.write_text(
        '{"schema":"single_owner_writer_map.v1","source_sha256":"' + SOURCE
        + '","dispositions":[],"unused":NaN}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-finite"):
        load_writer_map(path, source_sha256=SOURCE)
