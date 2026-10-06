"""Operation-specific behavior coverage for unlinked local_ai_coord actions."""

from local_ai_hub import mcp_server


class CoordBackend:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def coord(self, **payload):
        self.calls.append(payload)
        return self.response


class ApiBackend:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, payload, **kwargs):
        self.calls.append((path, payload, kwargs))
        return self.response


def test_local_ai_coord_task_get_forwards_task_and_root_identity(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = CoordBackend(
        {"success": True, "summary": "task t-get-1 is active", "task": {"task_id": "t-get-1", "status": "active"}}
    )
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_get", task_id="t-get-1", root=root, include_stale=True
    )

    assert backend.calls == [{
        "action": "task_get", "task_id": "t-get-1", "contract": None,
        "checkpoint": None, "status": "", "reason": "", "root": root,
        "ttl_seconds": 0, "include_stale": True,
    }]
    assert result["success"] is True
    assert result["summary"] == "task t-get-1 is active"


def test_local_ai_coord_task_checkpoint_preserves_checkpoint_payload(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    checkpoint = {"phase": "verify", "next_action": "run focused suite", "revision": "r17"}
    backend = CoordBackend({"success": True, "summary": "checkpoint recorded for t-check-1"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_checkpoint", task_id="t-check-1", checkpoint=checkpoint, root=root
    )

    assert backend.calls == [{
        "action": "task_checkpoint", "task_id": "t-check-1", "contract": None,
        "checkpoint": checkpoint, "status": "", "reason": "", "root": root,
        "ttl_seconds": 0, "include_stale": False,
    }]
    assert result["success"] is True
    assert result["summary"] == "checkpoint recorded for t-check-1"


def test_local_ai_coord_task_transition_forwards_target_state_and_reason(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = CoordBackend({"success": True, "summary": "task t-transition-1 moved to verifying"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_transition", task_id="t-transition-1", status="verifying",
        reason="focused checks are ready", root=root,
    )

    assert backend.calls == [{
        "action": "task_transition", "task_id": "t-transition-1", "contract": None,
        "checkpoint": None, "status": "verifying", "reason": "focused checks are ready",
        "root": root, "ttl_seconds": 0, "include_stale": False,
    }]
    assert result["success"] is True
    assert result["summary"] == "task t-transition-1 moved to verifying"


def test_local_ai_coord_task_list_forwards_status_and_stale_filter(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = CoordBackend({"success": True, "summary": "one active task", "tasks": [{"task_id": "t-list-1"}]})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_list", status="active", root=root, include_stale=True
    )

    assert backend.calls == [{
        "action": "task_list", "task_id": "", "contract": None,
        "checkpoint": None, "status": "active", "reason": "", "root": root, "query": "",
        "ttl_seconds": 0, "include_stale": True,
    }]
    assert result["success"] is True
    assert result["summary"] == "one active task"


def test_local_ai_coord_task_complete_forwards_reason_and_identity(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = CoordBackend({"success": True, "summary": "task t-done-1 completed"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="task_complete", task_id="t-done-1", reason="acceptance receipts attached", root=root
    )

    assert backend.calls == [{
        "action": "task_complete", "task_id": "t-done-1", "contract": None,
        "checkpoint": None, "status": "", "reason": "acceptance receipts attached",
        "root": root, "ttl_seconds": 0, "include_stale": False,
    }]
    assert result["success"] is True
    assert result["summary"] == "task t-done-1 completed"


def test_local_ai_coord_memo_put_posts_root_key_value_and_ttl(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = ApiBackend({"success": True, "summary": "memo stored", "key": "handoff:cli"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="memo_put", root=root, key="handoff:cli", value="CLI audit complete",
        ttl_seconds=3600,
    )

    assert backend.calls == [(
        "/api/memory/put",
        {"root": root, "key": "handoff:cli", "value": "CLI audit complete", "ttl_seconds": 3600},
        {},
    )]
    assert result["success"] is True
    assert result["summary"] == "memo stored"


def test_local_ai_coord_memo_search_posts_query_with_root_scope(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = ApiBackend({"success": True, "summary": "one matching memo", "records": [{"key": "handoff:cli"}]})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="memo_search", root=root, query="CLI audit"
    )

    assert backend.calls == [(
        "/api/memory/search", {"root": root, "query": "CLI audit", "limit": 12}, {}
    )]
    assert result["success"] is True
    assert result["summary"] == "one matching memo"


def test_local_ai_coord_memo_delete_posts_exact_root_and_key(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    backend = ApiBackend({"success": True, "summary": "memo deleted", "key": "handoff:old"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="memo_delete", root=root, key="handoff:old"
    )

    assert backend.calls == [
        ("/api/memory/delete", {"root": root, "key": "handoff:old"}, {})
    ]
    assert result["success"] is True
    assert result["summary"] == "memo deleted"


def test_local_ai_coord_claim_forwards_owned_paths_and_lease_identity(monkeypatch, tmp_path):
    root = str(tmp_path.resolve())
    paths = ["tools/surface_inventory.py", "tests/test_surface_inventory.py"]
    backend = ApiBackend({"success": True, "summary": "lease granted", "lease_id": "lease-42"})
    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", backend)

    result = mcp_server.local_ai_coord(
        action="claim", root=root, paths=paths, ttl_seconds=1200, value="T01 matcher tests"
    )

    assert backend.calls == [(
        "/api/leases/claim_batch",
        {"root": root, "paths": paths, "ttl_seconds": 1200, "purpose": "T01 matcher tests"},
        {},
    )]
    assert result["success"] is True
    assert result["summary"] == "lease granted"
