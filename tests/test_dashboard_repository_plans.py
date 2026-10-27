from __future__ import annotations

from local_ai_hub.dashboard import DASHBOARD_HTML


def test_project_board_requires_repository_and_plan_filter() -> None:
    assert 'id="coordBoardRoot"' in DASHBOARD_HTML
    assert 'id="coordBoardPlan"' in DASHBOARD_HTML
    start = DASHBOARD_HTML.index("async function loadCoordinationView()")
    end = DASHBOARD_HTML.index("function renderKanbanBoard()", start)
    loader = DASHBOARD_HTML[start:end]
    assert "/api/coord/plan_list" in loader
    assert "/api/coord/plan_board_view" in loader
    assert "JSON.stringify({root,plan_id:planId})" in loader
    assert "/api/coord/board_item_list" not in loader
    assert "global legacy board is not used" in loader


def test_dashboard_plan_edits_write_the_selected_repository_plan() -> None:
    start = DASHBOARD_HTML.index("async function updateCardStatus(")
    end = DASHBOARD_HTML.index("async function releaseSemaphore(", start)
    task_actions = DASHBOARD_HTML[start:end]
    assert "/api/coord/plan_task_edit" in task_actions
    assert "/api/coord/plan_task_delete" in task_actions
    assert "/api/coord/board_item_update" not in task_actions
    assert "/api/coord/board_item_delete" not in task_actions

    assert "/api/coord/plan_create" in DASHBOARD_HTML
    assert "/api/coord/plan_update" in DASHBOARD_HTML
    assert "function editPlanTask(planId,taskId)" in DASHBOARD_HTML
    assert "expected_revision" in task_actions
