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
    start = DASHBOARD_HTML.index("async function loadCoordinationView(")
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


def test_board_and_progress_distinguish_declared_and_verified_completion() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    board = DASHBOARD_HTML[DASHBOARD_HTML.index("function renderKanbanBoard(){"):
                           DASHBOARD_HTML.index("function renderSemaphoresTable(){")]
    progress = DASHBOARD_HTML[DASHBOARD_HTML.index("function renderPlanProgressView(){"):
                              DASHBOARD_HTML.index("function updateCoordOverviewCards(){")]
    harness = r"""
const nodes={kanbanBoardContainer:{},coordPlanProgressGrid:{}};
const $=id=>nodes[id]||null;
const esc=value=>String(value);
const cachedPlanItems=[];
const coordinationLoadErrors={};
const cachedPlanBoard={project_root:'repo',columns:{done:[]}};
const cachedBoardItems=[
  {plan_id:'p',plan_title:'Plan',task_id:'a',title:'Declared',status:'done',work_status:'done',verified:false},
  {plan_id:'p',plan_title:'Plan',task_id:'b',title:'Verified',status:'done',work_status:'done',verified:true}
];
""" + board + progress + r"""
renderKanbanBoard(); renderPlanProgressView();
console.log(JSON.stringify({board:nodes.kanbanBoardContainer.innerHTML,progress:nodes.coordPlanProgressGrid.innerHTML}));
"""
    result = subprocess.run([node, "-e", harness], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert "Unverified" in rendered["board"]
    assert "Verified" in rendered["board"]
    assert "50% verified complete" in rendered["progress"]
    assert "1 awaiting verification" in rendered["progress"]


def test_dashboard_task_edit_sends_only_canonical_coordination_fields() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    start = DASHBOARD_HTML.index("async function submitPlanTaskEdit(")
    end = DASHBOARD_HTML.index("function openAcquireSemModal(", start)
    source = DASHBOARD_HTML[start:end]
    harness = r"""
let activePlanTaskEdit={root:'C:/repo',planId:'plan_alpha',taskId:'task_beta',revision:'rev-1'};
const values={editTaskTitle:'Updated',editTaskDescription:'Details',editTaskOwner:'agent',
  editTaskNextAction:'Continue',editTaskBlocker:'Waiting',editTaskAcceptance:'One\nTwo',editTaskStatus:'blocked'};
const $=id=>id==='modalClose'?{click(){}}:(id in values?{value:values[id]}:null);
let request;
const post=async(path,payload)=>{request={path,payload};return {success:true};};
const coordOperationId=()=> 'operation-1';
const loadCoordinationView=async()=>{};
const alert=message=>{throw Error(message);};
""" + source + r"""
submitPlanTaskEdit({preventDefault(){}}).then(()=>console.log(JSON.stringify(request)));
"""
    completed = subprocess.run([node, "-e", harness], capture_output=True, text=True, check=True, timeout=10)
    request = json.loads(completed.stdout)
    assert request["path"] == "/api/coord/plan_task_edit"
    assert set(request["payload"]) == {
        "root", "plan_id", "task_id", "expected_revision", "task_data", "owner", "idempotency_key"
    }
    assert request["payload"]["plan_id"] == "plan_alpha"
    assert request["payload"]["task_id"] == "task_beta"
    assert request["payload"]["expected_revision"] == "rev-1"
    assert request["payload"]["task_data"]["work_status"] == "blocked"
    assert request["payload"]["task_data"]["acceptance_criteria"] == ["One", "Two"]


def test_created_plan_is_selected_when_board_refreshes() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    start = DASHBOARD_HTML.index("async function submitCreatePlan(")
    end = DASHBOARD_HTML.index("function openEditPlanModal(", start)
    source = DASHBOARD_HTML[start:end]
    harness = r"""
const elements={coordBoardRoot:{value:'C:/repo'},newPlanId:{value:'plan_new'},
  newPlanTitle:{value:'New plan'},newPlanDescription:{value:''},
  coordBoardPlan:{value:''},modalClose:{click(){}}};
const $=id=>elements[id]||null;
let selected;
const post=async()=>({success:true});
const coordOperationId=()=> 'operation-1';
const loadCoordinationView=async(id)=>{selected=id;};
const alert=message=>{throw Error(message);};
""" + source + r"""
submitCreatePlan({preventDefault(){}}).then(()=>console.log(JSON.stringify({selected})));
"""
    completed = subprocess.run([node, "-e", harness], capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(completed.stdout).get("selected") == "plan_new"


def test_plan_filter_can_select_a_newly_loaded_plan() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    start = DASHBOARD_HTML.index("function renderCoordPlanFilter(")
    end = DASHBOARD_HTML.index("async function loadCoordinationView(", start)
    source = DASHBOARD_HTML[start:end]
    harness = r"""
const select={value:'',innerHTML:''}; const edit={disabled:true};
const $=id=>({coordBoardPlan:select,coordEditPlanBtn:edit})[id]||null;
const esc=value=>String(value);
""" + source + r"""
renderCoordPlanFilter([{id:'plan_new',title:'New',lifecycle:'active'}],'plan_new');
console.log(JSON.stringify({value:select.value,disabled:edit.disabled}));
"""
    completed = subprocess.run([node, "-e", harness], capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(completed.stdout) == {"value": "plan_new", "disabled": False}


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
