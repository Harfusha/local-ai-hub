from __future__ import annotations

import json
from pathlib import Path
import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_incidents import (
    build_project_incident_record,
    list_project_incidents,
    load_project_incident,
    validate_project_incident_payload,
)
from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError


def _setup_repo(tmp_path: Path) -> RepoKnowledgeStore:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai-hub").mkdir()
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")
    (root / ".local-ai-hub/agent-os/incidents").mkdir(parents=True)
    return RepoKnowledgeStore(root)


def test_build_and_validate_canonical_incident(tmp_path: Path):
    store = _setup_repo(tmp_path)
    inc_input = {
        "incident_id": "inc-db-lock",
        "operation_class": "command",
        "error_class": "sqlite3.OperationalError",
        "signature_hash": "a1b2c3d4e5f60718293a",
        "resolved": True,
        "redacted_message": "database is locked under concurrent test run",
        "root_cause": "Unclosed SQLite connection in worker fixture",
        "verified_fix": "Add closing() context manager in pytest db teardown fixture",
        "confidence": 1.0,
        "affected_paths": ["tests/conftest.py"],
    }
    record = build_project_incident_record(store, inc_input)
    assert record["kind"] == "incident"
    assert record["id"] == "inc-db-lock"

    inc_file = store.root / ".local-ai-hub/agent-os/incidents/inc-db-lock.json"
    inc_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

    loaded = load_project_incident(store.root, "inc-db-lock")
    assert loaded["id"] == "inc-db-lock"

    all_inc = list_project_incidents(store.root, resolved_only=True)
    assert len(all_inc) == 1
    assert all_inc[0]["payload"]["root_cause"] == "Unclosed SQLite connection in worker fixture"


def test_incident_rejects_trivial_resolved(tmp_path: Path):
    store = _setup_repo(tmp_path)
    trivial_input = {
        "incident_id": "inc-trivial",
        "operation_class": "agent",
        "error_class": "RuntimeError",
        "signature_hash": "1122334455667788",
        "resolved": True,
        "redacted_message": "fail",
        "verified_fix": "resolved",
    }
    with pytest.raises(RepoPlanValidationError, match="verified_fix must describe the actual fix"):
        build_project_incident_record(store, trivial_input)


def test_incident_does_not_treat_string_false_as_resolved(tmp_path: Path):
    store = _setup_repo(tmp_path)
    with pytest.raises(RepoPlanValidationError):
        build_project_incident_record(store, {
            "incident_id": "inc-false-string",
            "operation_class": "agent",
            "error_class": "RuntimeError",
            "signature_hash": "1122334455667788",
            "resolved": "false",
            "verified_fix": "This must not turn an unresolved incident into a resolved one",
        })


def test_incident_rejects_bearer_token_in_redacted_message(tmp_path: Path):
    store = _setup_repo(tmp_path)
    with pytest.raises(RepoPlanValidationError):
        build_project_incident_record(store, {
            "incident_id": "inc-leaked-token",
            "operation_class": "mcp",
            "error_class": "PermissionError",
            "signature_hash": "1122334455667788",
            "resolved": False,
            "redacted_message": "Authorization: Bearer eyJhbGciOiJub25lIn0.private-session-token",
        })


def test_incident_rejects_nonfinite_confidence(tmp_path: Path):
    store = _setup_repo(tmp_path)
    with pytest.raises(RepoPlanValidationError, match="confidence must be finite"):
        build_project_incident_record(store, {
            "incident_id": "inc-invalid-confidence",
            "operation_class": "verification",
            "error_class": "RuntimeError",
            "signature_hash": "1122334455667788",
            "resolved": False,
            "confidence": float("nan"),
        })
