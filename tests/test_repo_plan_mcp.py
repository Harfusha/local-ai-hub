from __future__ import annotations

from local_ai_hub.client import HubClient
from local_ai_hub import mcp_server


def test_plan_action_ignores_shared_changed_paths_transport_metadata(monkeypatch, tmp_path):
    forwarded = {}

    class FakeClient:
        def coord(self, **kwargs):
            forwarded.update(kwargs)
            return {"success": True, "plans": []}

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())
    monkeypatch.setattr(mcp_server, "_compact", lambda value, *_args: value)

    result = mcp_server.local_ai_coord(
        action="plan_list",
        root=str(tmp_path),
        changed_paths=["src/changed.py"],
    )

    assert result == {"success": True, "plans": []}
    assert forwarded == {"action": "plan_list", "root": str(tmp_path)}


def test_plan_action_still_rejects_other_unrelated_arguments(monkeypatch, tmp_path):
    class FakeClient:
        def coord(self, **_kwargs):  # pragma: no cover - contract must reject first
            raise AssertionError("invalid plan arguments reached the client")

    monkeypatch.setattr(mcp_server.FEATURES, "coord", True)
    monkeypatch.setattr(mcp_server, "CLIENT", FakeClient())

    result = mcp_server.local_ai_coord(
        action="plan_list",
        root=str(tmp_path),
        changed_paths=["src/changed.py"],
        id="not-a-plan-list-field",
    )

    assert result["success"] is False
    assert "id" in result["error"]


def test_hub_client_drops_shared_changed_paths_before_plan_contract_validation(monkeypatch, tmp_path):
    client = HubClient(auto_start=False)
    forwarded = {}

    def fake_post(path, payload):
        forwarded.update(path=path, payload=payload)
        return {"success": True, "plans": []}

    monkeypatch.setattr(client, "post", fake_post)

    result = client.coord(
        action="plan_list",
        root=str(tmp_path),
        changed_paths=["src/changed.py"],
    )

    assert result == {"success": True, "plans": []}
    assert forwarded == {
        "path": "/api/coord/plan_list",
        "payload": {"root": str(tmp_path)},
    }
