from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from local_ai_hub.project_identity import project_scope_id, worktree_scope_id
from local_ai_hub.process_utils import clean_git_env
from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.repo_project_memory import build_project_memory_record, load_project_memory


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        text=True, timeout=15, env=clean_git_env(),
    )


def test_project_identity_survives_checkout_relocation(tmp_path: Path):
    project_id = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    checkout = tmp_path / "checkout-a"
    relocated = tmp_path / "checkout-b"
    checkout.mkdir()
    _git(checkout, "init")
    _git(checkout, "config", "user.email", "fixture@example.invalid")
    _git(checkout, "config", "user.name", "Relocation fixture")
    local = checkout / ".local-ai-hub"
    local.mkdir()
    (local / "project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project_id, "mode": "shared",
    }), encoding="utf-8")
    store = RepoKnowledgeStore(checkout)
    record = build_project_memory_record(store, {
        "record_id": "mem-relocation",
        "kind": "fact",
        "scope": "project",
        "key": "checkout_relocation",
        "value": "Project records survive moving the Git checkout.",
    })
    memory_path = local / "agent-os" / "memory" / "mem-relocation.json"
    memory_path.parent.mkdir(parents=True)
    memory_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "seed canonical project memory")
    original_worktree_id = worktree_scope_id(checkout)

    shutil.move(str(checkout), str(relocated))

    assert project_scope_id(relocated) == project_id
    assert worktree_scope_id(relocated) != original_worktree_id
    assert load_project_memory(relocated, "mem-relocation")["payload"]["value"] == (
        "Project records survive moving the Git checkout."
    )


def test_non_git_workspace_scope_is_local_and_deterministic(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()

    assert project_scope_id(root) == project_scope_id(root)
    assert project_scope_id(root) != project_scope_id(tmp_path)


def test_local_ai_hub_checkout_has_a_portable_project_identity():
    root = Path(__file__).resolve().parents[1]
    project_id = project_scope_id(root)

    assert str(UUID(project_id)) == project_id


def test_git_checkout_requires_update_migrated_project_manifest(tmp_path: Path):
    checkout = tmp_path / "old-checkout"
    checkout.mkdir()
    _git(checkout, "init")

    with pytest.raises(ValueError, match="stable project_id"):
        project_scope_id(checkout)

    project_id = str(uuid4())
    manifest = checkout / ".local-ai-hub" / "project.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"schema_version": 1, "project_id": project_id}), encoding="utf-8"
    )
    assert project_scope_id(checkout) == project_id
    _git(checkout, "config", "--local", "local-ai-hub.project-id", str(uuid4()))
    with pytest.raises(ValueError, match="conflicts with project manifest"):
        project_scope_id(checkout)
