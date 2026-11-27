from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from local_ai_hub.project_identity import project_scope_id, worktree_scope_id


def test_project_identity_survives_checkout_relocation(tmp_path: Path):
    project_id = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    roots = [tmp_path / "checkout-a", tmp_path / "checkout-b"]
    for root in roots:
        local = root / ".local-ai-hub"
        local.mkdir(parents=True)
        (local / "project.json").write_text(json.dumps({
            "schema_version": 1, "project_id": project_id, "mode": "shared",
        }), encoding="utf-8")

    assert project_scope_id(roots[0]) == project_id
    assert project_scope_id(roots[1]) == project_id
    assert worktree_scope_id(roots[0]) != worktree_scope_id(roots[1])


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
    subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)

    with pytest.raises(ValueError, match="stable project_id"):
        project_scope_id(checkout)

    project_id = str(uuid4())
    manifest = checkout / ".local-ai-hub" / "project.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"schema_version": 1, "project_id": project_id}), encoding="utf-8"
    )
    assert project_scope_id(checkout) == project_id
