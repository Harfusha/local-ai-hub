from __future__ import annotations

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.client import HubClient


class FakeCoordClient:
    def __init__(self) -> None:
        self.calls = []

    def post(self, path, payload, **kwargs):
        self.calls.append(("post", path, payload, kwargs))
        return {"success": True}

    def get(self, path, **kwargs):
        self.calls.append(("get", path, None, kwargs))
        return {"success": True}

    def coord(self, **kwargs):
        self.calls.append(("coord", kwargs.get("action"), kwargs, {}))
        return {"success": True}


def _client(monkeypatch):
    fake = FakeCoordClient()
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", fake)
    return fake


def test_swarm_actions_forward_canonical_values_and_empty_payload(monkeypatch, tmp_path) -> None:
    fake = _client(monkeypatch)

    mcp_server.local_ai_coord(
        action="swarm_dispatch", root=str(tmp_path), goal="goal", target_paths=[],
        test_command="", author="agent-x",
    )
    mcp_server.local_ai_coord(
        action="swarm_step", root=str(tmp_path), swarm_id="swarm-1", role="Reviewer",
        swarm_action="submit_patch", payload={},
    )
    mcp_server.local_ai_coord(action="swarm_status", root=str(tmp_path), swarm_id="swarm-1")
    mcp_server.local_ai_coord(action="swarm_list", root=str(tmp_path), state="active")
    mcp_server.local_ai_coord(action="swarm_cancel", root=str(tmp_path), swarm_id="swarm-1", reason="")

    dispatch = fake.calls[0][2]
    assert dispatch == {
        "goal": "goal", "target_paths": [], "test_command": "", "author": "agent-x", "root": str(tmp_path),
    }
    step = fake.calls[1][2]
    assert step["swarm_id"] == "swarm-1"
    assert step["role"] == "Reviewer"
    assert step["action"] == "submit_patch"
    assert step["payload"] == {}
    assert "swarm-1" in fake.calls[2][2]
    assert "state=active" in fake.calls[3][2]
    assert fake.calls[4][2]["reason"] == ""


def test_worktree_merge_and_dataset_actions_keep_canonical_types_and_defaults(monkeypatch, tmp_path) -> None:
    fake = _client(monkeypatch)

    mcp_server.local_ai_coord(action="worktree_lease", root=str(tmp_path), branch="")
    mcp_server.local_ai_coord(
        action="worktree_release", root=str(tmp_path), worktree_id="wt-1",
        worktree_path="", delete_branch=False, branch="",
    )
    mcp_server.local_ai_coord(
        action="worktree_release", root=str(tmp_path), worktree_id="wt-2",
    )
    mcp_server.local_ai_coord(
        action="simulate_merge", root=str(tmp_path), source_branch="feature", target_branch="main",
    )
    mcp_server.local_ai_coord(action="curate_dataset")

    lease = fake.calls[0][2]
    assert lease == {"action": "worktree_lease", "root": str(tmp_path), "branch": None}
    release = fake.calls[1][2]
    assert release["worktree_path"] == ""
    assert release["worktree_id"] == "wt-1"
    assert release["delete_branch"] is False
    assert release["branch"] is None
    assert fake.calls[2][2]["delete_branch"] is True
    assert fake.calls[3][2] == {
        "action": "simulate_merge", "root": str(tmp_path),
        "source_branch": "feature", "target_branch": "main",
    }
    dataset = fake.calls[4][2]
    assert dataset["action"] == "curate_dataset"
    assert dataset["output_path"] == "training_dataset.jsonl"
    assert dataset["min_receipts"] == 1
    assert dataset["format"] == "jsonl"


def test_retired_aliases_and_boolean_receipt_threshold_are_rejected(monkeypatch, tmp_path) -> None:
    fake = _client(monkeypatch)
    rejected = mcp_server.local_ai_coord(
        action="swarm_dispatch", goal="canonical", task="retired alias", root=str(tmp_path),
    )
    assert rejected["success"] is False
    assert not fake.calls

    rejected = mcp_server.local_ai_coord(action="curate_dataset", min_receipts=False)
    assert rejected["success"] is False
    assert not fake.calls

    rejected = mcp_server.local_ai_coord(action="curate_training_dataset")
    assert rejected["success"] is False
    assert not fake.calls


@pytest.mark.parametrize(
    ("action", "canonical", "retired"),
    [
        ("swarm_dispatch", {"goal": "goal"}, {"task": "old goal"}),
        ("swarm_step", {"swarm_id": "swarm"}, {"key": "old id"}),
        ("swarm_status", {"swarm_id": "swarm"}, {"task_id": "old id"}),
        ("swarm_list", {"state": "active"}, {"status": "active"}),
        ("swarm_cancel", {"swarm_id": "swarm"}, {"value": "old id"}),
        ("worktree_lease", {"branch": "branch"}, {"key": "old branch"}),
        ("worktree_release", {"worktree_id": "wt"}, {"status": "false"}),
        ("simulate_merge", {"source_branch": "source"}, {"key": "old source"}),
        ("curate_dataset", {}, {"query": "old output path"}),
    ],
)
def test_canonical_actions_reject_nonempty_retired_fields(monkeypatch, action, canonical, retired) -> None:
    fake = _client(monkeypatch)
    result = mcp_server.local_ai_coord(action=action, **canonical, **retired)
    assert result["success"] is False
    assert not fake.calls


def test_verify_export_omitted_format_keeps_markdown_default(monkeypatch, tmp_path) -> None:
    fake = _client(monkeypatch)
    monkeypatch.setattr(
        mcp_server, "load_operational_mode",
        lambda *_args, **_kwargs: mcp_server.OperationalModeSnapshot("active", 1, None),
    )
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server, "_record_adoption", lambda *_args, **_kwargs: None)
    mcp_server.local_ai_coord(action="verify_export", task_id="task-1", root=str(tmp_path))
    assert fake.calls[0][1] == "/api/agent-state/verification"
    assert fake.calls[0][2] == {
        "action": "export", "task_id": "task-1", "root": str(tmp_path), "format": "markdown",
    }


def test_hub_client_coord_fallbacks_forward_canonical_fields_only() -> None:
    client = object.__new__(HubClient)
    calls = []
    client.post = lambda path, payload: calls.append((path, payload)) or {"success": True}

    client.coord(action="worktree_lease", root="repo", branch="")
    client.coord(
        action="worktree_release", root="repo", worktree_path="", worktree_id="wt-1",
        delete_branch=False, branch="", value="retired", lease_id="retired",
    )
    client.coord(action="worktree_release", root="repo", worktree_id="wt-2")
    client.coord(
        action="simulate_merge", root="repo", source_branch="source", target_branch="",
        key="retired", branch="retired", target_scope="retired",
    )

    assert calls[0] == ("/api/coord/worktree_lease", {"root": "repo", "branch": None})
    assert calls[1] == ("/api/coord/worktree_release", {
        "root": "repo", "worktree_path": "", "worktree_id": "wt-1",
        "delete_branch": False, "branch": None,
    })
    assert calls[2] == ("/api/coord/worktree_release", {
        "root": "repo", "worktree_path": "", "worktree_id": "wt-2",
        "delete_branch": True, "branch": None,
    })
    assert calls[3] == ("/api/coord/simulate_merge", {
        "root": "repo", "source_branch": "source", "target_branch": "",
    })
