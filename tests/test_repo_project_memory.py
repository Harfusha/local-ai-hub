from __future__ import annotations

import json
from pathlib import Path
import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_memory import (
    build_project_memory_record,
    list_project_memory,
    load_project_memory,
    validate_project_memory_payload,
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
    (root / ".local-ai-hub/agent-os/memory").mkdir(parents=True)
    return RepoKnowledgeStore(root)


def test_build_and_validate_canonical_memory(tmp_path: Path):
    store = _setup_repo(tmp_path)
    mem_input = {
        "record_id": "mem-cache-pattern",
        "kind": "pattern",
        "scope": "project",
        "key": "test_result_cache_rule",
        "value": "Never skip regressions or coverage checks using test cache",
        "confidence": 0.95,
        "source": "developer_guide",
        "sensitivity": "internal",
    }
    record = build_project_memory_record(store, mem_input)
    assert record["kind"] == "memory"
    assert record["id"] == "mem-cache-pattern"

    mem_file = store.root / ".local-ai-hub/agent-os/memory/mem-cache-pattern.json"
    mem_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

    loaded = load_project_memory(store.root, "mem-cache-pattern")
    assert loaded["id"] == "mem-cache-pattern"

    all_mem = list_project_memory(store.root)
    assert len(all_mem) == 1
    assert all_mem[0]["payload"]["key"] == "test_result_cache_rule"


def test_memory_rejects_credentials_and_session_tokens(tmp_path: Path):
    store = _setup_repo(tmp_path)
    leaky_input = {
        "record_id": "mem-leaky",
        "kind": "fact",
        "scope": "project",
        "key": "api_config",
        "value": {"session_id": "sess-secret-12345", "token": "ghp_secret"},
    }
    with pytest.raises(RepoPlanValidationError, match="private session, receipt, or credential data"):
        build_project_memory_record(store, leaky_input)


@pytest.mark.parametrize("value", [
    "Deployment password: CorrectHorseBatteryStaple-9284",
    "Authorization: Bearer eyJhbGciOiJub25lIn0.private-session-token",
    {"runtime": {"sessionId": "private-session-9284"}},
])
def test_memory_rejects_private_data_in_realistic_value_content(tmp_path: Path, value: object):
    store = _setup_repo(tmp_path)
    with pytest.raises(RepoPlanValidationError):
        build_project_memory_record(store, {
            "record_id": "mem-private-value",
            "kind": "rule",
            "scope": "project",
            "key": "deployment_guidance",
            "value": value,
        })


def test_memory_rejects_confidential_content_from_shared_git_store(tmp_path: Path):
    store = _setup_repo(tmp_path)
    with pytest.raises(RepoPlanValidationError, match="confidential memory cannot be published"):
        build_project_memory_record(store, {
            "record_id": "mem-confidential",
            "kind": "fact",
            "scope": "project",
            "key": "private_customer_data",
            "value": "Customer credential details",
            "sensitivity": "confidential",
        })
