"""Public planner regressions against real file-backed workspace operations."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.client import HubClient
from local_ai_hub.operation_contracts import operation_input_schema, validate_operation_arguments
from local_ai_hub.repo_plan import RepoPlanConflictError
from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace
from local_ai_hub.services import LocalAIServices


@pytest.fixture
def public_planner(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"server": {"state_dir": str(tmp_path / "state")},
                       "security": {"allowed_roots": [str(root)]}}
    return services, str(root)


def test_real_public_plan_lifecycle(public_planner):
    services, root = public_planner
    assert services.plan_init(root=root)["success"]
    created = services.plan_create(root=root, plan_id="plan_release", title="Release")
    assert created["success"]
    listed = services.plan_list(root=root)
    assert [p["id"] for p in listed["plans"]] == ["plan_release"]
    updated = services.plan_update(root=root, plan_id="plan_release", title="Ready",
                                   expected_revision=created["file_revision"])
    assert updated["plan"]["title"] == "Ready"
    edited = services.plan_task_edit(root=root, plan_id="plan_release", task_id="task_parser",
                                    task_data={"title": "Parser", "work_status": "in_progress"},
                                    expected_revision=updated["file_revision"])
    assert edited["success"]
    board = services.plan_board_view(root=root)
    assert board["columns"]["in_progress"][0]["task_id"] == "task_parser"
    with pytest.raises(RepoPlanConflictError, match="active or unintegrated"):
        services.plan_task_delete(root=root, plan_id="plan_release", task_id="task_parser",
                                  expected_revision=edited["file_revision"])
    reset = services.plan_task_edit(root=root, plan_id="plan_release", task_id="task_parser",
                                    task_data={"work_status": "planned"},
                                    expected_revision=edited["file_revision"])
    deleted = services.plan_task_delete(root=root, plan_id="plan_release", task_id="task_parser",
                                        expected_revision=reset["file_revision"])
    assert deleted["success"]
    assert services.plan_validate(root=root, plan_id="plan_release")["valid"]
    archived = services.plan_archive(root=root, plan_id="plan_release",
                                     expected_revision=deleted["file_revision"])
    assert archived["plan"]["lifecycle"] == "archived"


@pytest.mark.parametrize("revision", [0, False, "", [], {}])
def test_public_revision_rejects_coercion(public_planner, revision):
    services, root = public_planner
    created = services.plan_create(root=root, plan_id="plan_release", title="Release")
    with pytest.raises(ValueError, match="expected_revision"):
        services.plan_update(root=root, plan_id="plan_release", expected_revision=revision, title="Bad")
    assert RepoPlanWorkspace(root).get_plan("plan_release")["file_revision"] == created["file_revision"]


@pytest.mark.parametrize("root", ["", ".", 7, False])
def test_public_root_requires_explicit_absolute_directory(public_planner, root):
    services, _ = public_planner
    with pytest.raises(ValueError, match="root"):
        services.plan_list(root=root)


def test_public_root_authorization_applies_before_workspace_creation(public_planner, tmp_path):
    services, _ = public_planner
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    with pytest.raises(ValueError, match="allowed_roots"):
        services.plan_init(root=str(foreign))
    assert not (foreign / ".local-ai-hub").exists()


def test_explicit_root_never_uses_legacy_global_board(public_planner):
    services, root = public_planner
    services._ensure_board = lambda: pytest.fail("global legacy board accessed")
    summary = services.board_summary(root=root)
    assert summary["success"] and summary["source"] == "repo_plan"
    assert summary["total_items"] == 0
    assert services.board_item_list(root=root)["items"] == []
    briefing = services.session_briefing(root=root, include=["board", "plans"])
    assert briefing["board"]["recent_items"] == []
    assert briefing["plans"] == []


def test_source_ready_is_not_delivered_done(public_planner):
    services, root = public_planner
    RepoPlanWorkspace(root).create_plan("plan_release", "Release", tasks={
        "task_parser": {"title": "Parser", "work_status": "source_ready"}})
    summary = services.board_summary(root=root)
    assert summary["counts"]["source_ready"] == 1
    assert summary["counts"]["done"] == 0


@pytest.mark.parametrize("action,field", [
    ("plan_list", "include_archived"), ("plan_create", "goal"),
    ("plan_create", "target_branch"), ("plan_create", "specs"),
    ("plan_update", "status"), ("plan_update", "decisions"),
    ("plan_archive", "archive_reason"), ("plan_board_view", "owner"),
])
def test_planner_contract_rejects_retired_aliases(action, field):
    assert validate_operation_arguments("local_ai_coord", action, {field: "legacy"})


def test_revision_schema_is_content_revision_string():
    schema = operation_input_schema("local_ai_coord", "plan_update")
    assert schema["properties"]["expected_revision"]["type"] == "string"
    assert "root" in schema["required"]
    assert "expected_revision" in schema["required"]


def test_http_plan_endpoint_ignores_shared_changed_paths_transport_metadata(public_planner):
    from local_ai_hub.http_post_repository_analysis import handle_post_plan

    services, root = public_planner
    responses = []
    handler = SimpleNamespace(_send=lambda code, body: responses.append((code, body)))

    assert handle_post_plan(
        handler,
        {"root": root, "changed_paths": ["src/changed.py"]},
        "/api/coord/plan_list",
        SimpleNamespace(services=services),
    )
    code, body = responses[0]
    assert code == 200
    assert body["success"] is True
    assert body["plans"] == []


def test_real_http_client_mcp_plan_roundtrip(public_planner, monkeypatch):
    from local_ai_hub import mcp_server
    from local_ai_hub.http_post_repository_analysis import handle_post_plan

    services, root = public_planner
    responses = []
    handler = SimpleNamespace(_send=lambda code, body: responses.append((code, body)))
    client = HubClient.__new__(HubClient)

    def post(path, payload, **kwargs):
        assert handle_post_plan(handler, payload, path, SimpleNamespace(services=services))
        code, body = responses.pop()
        assert code < 500
        return body

    client.post = post
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_compact", lambda result, *args, **kwargs: result)
    call = getattr(mcp_server.local_ai_coord, "__wrapped__", mcp_server.local_ai_coord)
    created = call(action="plan_create", root=root, plan_id="plan_release", title="Release")
    assert created["success"]
    updated = call(action="plan_update", root=root, plan_id="plan_release", title="Ready",
                   expected_revision=created["file_revision"])
    assert updated["plan"]["title"] == "Ready"
    assert call(action="plan_list", root=root)["plans"][0]["title"] == "Ready"


def test_mcp_task_claim_keeps_task_action(monkeypatch):
    from local_ai_hub import mcp_server
    calls = []
    client = HubClient.__new__(HubClient)
    client.post = lambda path, payload, **kwargs: calls.append((path, payload)) or {"success": True}
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_compact", lambda result, *args, **kwargs: result)
    call = getattr(mcp_server.local_ai_coord, "__wrapped__", mcp_server.local_ai_coord)
    assert call(action="task_claim", root="C:/repo", task_id="task_123", owner="codex")["success"]
    assert calls[0][0] == "/api/agent-state/tasks"
    assert calls[0][1]["action"] == "claim"
    assert calls[0][1]["owner"] == "codex"
