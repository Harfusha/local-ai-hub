from __future__ import annotations

import json
from pathlib import Path
import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_tasks import (
    build_project_task_record,
    list_project_tasks,
    load_project_task,
    validate_project_task_payload,
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
    (root / ".local-ai-hub/agent-os/tasks").mkdir(parents=True)
    return RepoKnowledgeStore(root)


def test_build_and_validate_canonical_task(tmp_path: Path):
    store = _setup_repo(tmp_path)
    task_input = {
        "task_id": "task-v4-core",
        "status": "planned",
        "contract": {
            "goal": "Implement Git-first Agent OS",
            "description": "Full durable state migration",
            "acceptance_criteria": ["All tasks in git", "No private leaks"],
            "non_goals": ["Changing model routes"],
            "constraints": ["Offline migration first"],
            "risk_profile": "high",
        },
        "checkpoint": {
            "phase": "implementation",
            "next_action": "write tests",
            "blockers": [],
            "affected_paths": ["src/local_ai_hub/repo_project_tasks.py"],
        },
    }
    record = build_project_task_record(store, task_input)
    assert record["kind"] == "task"
    assert record["id"] == "task-v4-core"
    assert record["payload"]["contract"]["goal"] == "Implement Git-first Agent OS"

    # Save to disk and verify loading
    task_file = store.root / ".local-ai-hub/agent-os/tasks/task-v4-core.json"
    task_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

    loaded = load_project_task(store.root, "task-v4-core")
    assert loaded["id"] == "task-v4-core"

    all_tasks = list_project_tasks(store.root)
    assert len(all_tasks) == 1
    assert all_tasks[0]["id"] == "task-v4-core"


def test_task_validation_rejects_missing_criteria(tmp_path: Path):
    store = _setup_repo(tmp_path)
    invalid_task = {
        "task_id": "task-invalid",
        "status": "planned",
        "contract": {
            "goal": "Missing criteria",
            "description": "",
            "acceptance_criteria": [],
            "non_goals": [],
            "constraints": [],
            "risk_profile": "normal",
        },
        "checkpoint": {
            "phase": "", "next_action": "", "blockers": [], "affected_paths": [],
        },
    }
    with pytest.raises(RepoPlanValidationError, match="at least one acceptance criterion"):
        build_project_task_record(store, invalid_task)
