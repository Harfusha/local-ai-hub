from types import SimpleNamespace

import pytest

from local_ai_hub.http_post_repository_analysis import handle_post_plan
from local_ai_hub.repo_plan.schema_validation import RepoPlanConflictError, RepoPlanNotFoundError
from local_ai_hub.repo_plan.workspace import RepoPlanWorkspace


def test_invalid_plan_id_returns_actionable_client_error(tmp_path):
    responses = []
    handler = SimpleNamespace(_send=lambda status, payload: responses.append((status, payload)))
    workspace = RepoPlanWorkspace(tmp_path)
    app = SimpleNamespace(services=SimpleNamespace(
        plan_create=lambda root, plan_id, title: workspace.create_plan(plan_id, title)
    ))

    handled = handle_post_plan(handler, {
        "root": str(tmp_path), "plan_id": "wrong_prefix", "title": "Test",
    }, "/api/coord/plan_create", app)

    assert handled is True
    status, payload = responses[0]
    assert status == 400
    assert payload["success"] is False
    assert "Invalid plan ID" in payload["error"]


def test_board_http_reports_invalid_plan_instead_of_empty_success(tmp_path):
    responses = []
    handler = SimpleNamespace(_send=lambda status, payload: responses.append((status, payload)))
    workspace = RepoPlanWorkspace(tmp_path)
    workspace.init_workspace()
    (workspace.plans_dir / "plan_bad.plan.json").write_text("{invalid", encoding="utf-8")
    app = SimpleNamespace(services=SimpleNamespace(
        plan_board_view=lambda root: workspace.get_board_view()
    ))

    assert handle_post_plan(handler, {"root": str(tmp_path)}, "/api/coord/plan_board_view", app)
    status, payload = responses[0]
    assert status == 400
    assert payload["success"] is False
    assert "plan_bad" in payload["error"]


@pytest.mark.parametrize(("error", "expected_status"), [
    (RepoPlanConflictError("stale revision"), 409),
    (RepoPlanNotFoundError("plan missing"), 404),
])
def test_plan_http_preserves_conflict_and_missing_status(tmp_path, error, expected_status):
    responses = []
    handler = SimpleNamespace(_send=lambda status, payload: responses.append((status, payload)))

    def fail(**_kwargs):
        raise error

    app = SimpleNamespace(services=SimpleNamespace(plan_get=fail))
    assert handle_post_plan(handler, {"root": str(tmp_path), "plan_id": "plan_example"},
                            "/api/coord/plan_get", app) is True
    assert responses[0][0] == expected_status

