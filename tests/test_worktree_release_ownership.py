from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from local_ai_hub import process_utils
from local_ai_hub.client import HubClient


def test_worktree_release_fails_closed_without_owner_identifier(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Lease Fixture"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "lease-fixture@example.invalid"], cwd=repo, capture_output=True, check=True)
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=repo, capture_output=True, check=True)

    created = process_utils.create_git_worktree(repo, branch_name="owned-fixture")
    assert created["success"] is True
    target = Path(created["worktree_path"])
    try:
        denied = process_utils.remove_git_worktree(repo, target, branch_name="owned-fixture")
        assert denied["success"] is False
        assert "identifier is required" in denied["error"]
        assert target.is_dir()

        removed = process_utils.remove_git_worktree(
            repo, target, branch_name="owned-fixture", worktree_id=created["worktree_id"]
        )
        assert removed["success"] is True
        assert removed["worktree_id"] == created["worktree_id"]
        assert not target.exists()
    finally:
        if target.exists():
            subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(target)], capture_output=True)


def test_services_worktree_release_forwards_owner_identifier() -> None:
    source = Path(__file__).parents[1] / "src/local_ai_hub/services.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "worktree_release"
    )
    calls = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "remove_git_worktree"
    ]
    assert len(calls) == 1
    assert any(keyword.arg == "worktree_id" and isinstance(keyword.value, ast.Name)
               and keyword.value.id == "worktree_id" for keyword in calls[0].keywords)


def test_client_worktree_release_posts_owner_identifier(monkeypatch) -> None:
    client = HubClient.__new__(HubClient)
    seen = {}

    def post(path, payload):
        seen.update(path=path, payload=payload)
        return {"success": True}

    monkeypatch.setattr(client, "post", post)
    result = client.coord(
        "worktree_release", root="/repo", worktree_path="/tmp/wt", worktree_id="wt-123"
    )
    assert result["success"] is True
    assert seen["payload"]["worktree_id"] == "wt-123"


def test_mcp_worktree_release_passes_owner_identifier() -> None:
    source = Path(__file__).parents[1] / "src/local_ai_hub/mcp_server.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "coord"
        and any(keyword.arg == "action" and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "worktree_release" for keyword in node.keywords)
    ]
    assert len(calls) == 1
    assert any(keyword.arg == "worktree_id" and isinstance(keyword.value, ast.Name)
               and keyword.value.id == "worktree_id" for keyword in calls[0].keywords)

    protected = next(
        node.value for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_STATUS_PROTECTED_KEYS"
                for target in node.targets)
    )
    assert isinstance(protected, ast.Tuple)
    assert {item.value for item in protected.elts if isinstance(item, ast.Constant)} >= {
        "worktree_id", "worktree_path", "lease_id", "branch",
    }


def test_http_worktree_release_passes_owner_identifier() -> None:
    source = Path(__file__).parents[1] / "src/local_ai_hub/http_server.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "worktree_release"
    ]
    assert calls
    assert any(keyword.arg == "worktree_id" for call in calls for keyword in call.keywords)
