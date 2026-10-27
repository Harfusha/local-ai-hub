from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from local_ai_hub.dashboard import DASHBOARD_HTML
from local_ai_hub.repo_plan.schema_validation import PLAN_ID_REGEX


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


def test_dashboard_generates_plan_ids_accepted_by_repository_schema() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")

    start = DASHBOARD_HTML.index("function openCreatePlanModal()")
    end = DASHBOARD_HTML.index("async function submitCreatePlan(", start)
    source = DASHBOARD_HTML[start:end]
    harness = r"""
const elements={
  coordBoardRoot:{value:'C:\\repo'},
  modalTitle:{},modalLive:{},modalBody:{},
  modalBg:{classList:{add:()=>{}}},
  newPlanTitle:{value:'Local AI Hub 5.1.0 Finalization',addEventListener(_event,cb){this.listener=cb;}},
  newPlanId:{value:'',dataset:{},addEventListener(_event,cb){this.listener=cb;}}
};
const $=id=>elements[id]||null;
""" + source + r"""
openCreatePlanModal();
elements.newPlanTitle.listener();
const normal=elements.newPlanId.value;
elements.newPlanTitle.value='🚀';
elements.newPlanTitle.listener();
const empty=elements.newPlanId.value;
elements.newPlanId.value='plan_operator_choice';
elements.newPlanId.dataset.edited='true';
elements.newPlanTitle.value='Changed title';
elements.newPlanTitle.listener();
console.log(JSON.stringify({normal,empty,manual:elements.newPlanId.value}));
"""
    result = subprocess.run([node], input=harness, check=True, capture_output=True, text=True)
    generated = json.loads(result.stdout)

    assert generated["normal"] == "plan_local-ai-hub-5-1-0-finalization"
    assert generated["empty"] == "plan_new"
    assert generated["manual"] == "plan_operator_choice"
    assert PLAN_ID_REGEX.fullmatch(generated["normal"])
    assert PLAN_ID_REGEX.fullmatch(generated["empty"])
    assert 'pattern="plan_[A-Za-z0-9][A-Za-z0-9_-]{0,79}"' in DASHBOARD_HTML
    assert 'maxlength="85"' in DASHBOARD_HTML
