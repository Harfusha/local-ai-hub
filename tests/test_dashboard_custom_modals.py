from __future__ import annotations

import re
from local_ai_hub.dashboard import DASHBOARD_HTML


def test_dashboard_modal_css_classes_present() -> None:
    expected_classes = [
        ".modal-hero",
        ".modal-body-wrap",
        ".modal-card",
        ".modal-card-head",
        ".modal-card-body",
        ".modal-actions-bar",
        ".modal-form",
        ".modal-checklist",
        ".modal-checklist-item",
        ".modal-radio-option",
        ".doc-check-grid",
        ".doc-check-title",
        ".code-box",
        ".copy-btn",
    ]
    for cls in expected_classes:
        assert cls in DASHBOARD_HTML, f"Expected CSS class {cls} missing from DASHBOARD_HTML"


def test_dashboard_modal_renderers_defined() -> None:
    expected_renderers = [
        "function renderTaskModal(",
        "function renderMemoryModal(",
        "function renderIncidentModal(",
        "function renderLiveStreamModal(",
        "function renderProjectModal(",
        "function renderDoctorModal(",
        "function renderCodeIntelModal(",
        "function renderActiveLeaseModal(",
        "function renderActiveCommandModal(",
        "function renderErrorFingerprintModal(",
        "function openArchNodeModal(",
        "function renderDbOptModal(",
        "function renderCachePurgeModal(",
    ]
    for fn in expected_renderers:
        assert fn in DASHBOARD_HTML, f"Expected renderer function {fn} missing from DASHBOARD_HTML"


def test_dashboard_modal_forms_and_actions_defined() -> None:
    expected_actions = [
        "function openCreateTaskModal(",
        "async function submitCreateTask(",
        "function openRecordMemoryModal(",
        "async function submitRecordMemory(",
        "function openRecordIncidentModal(",
        "async function submitRecordIncident(",
        "function openCleanupModal(",
        "async function executeCleanupAction(",
        "function openRegisterProjectModal(",
        "async function submitRegisterProject(",
        "function openDeleteProjectModal(",
        "async function confirmDeleteProject(",
        "function openCleanMissingModal(",
        "async function confirmCleanMissing(",
        "async function openDoctorModal(",
        "async function checkTaskCompletionGate(",
        "async function checkTaskCriterion(",
        "async function completeTaskAction(",
        "function showFailTaskInput(",
        "async function submitFailTask(",
        "async function transitionTaskAction(",
        "async function deleteMemoryAction(",
        "async function resolveIncidentAction(",
        "async function releaseLeaseAction(",
    ]
    for act in expected_actions:
        assert act in DASHBOARD_HTML, f"Expected action/form function {act} missing from DASHBOARD_HTML"


def test_dashboard_type_inference_and_dispatcher() -> None:
    assert "function inferEntityType(obj)" in DASHBOARD_HTML
    assert "function openModal(obj,title='',entityType='')" in DASHBOARD_HTML
    assert "if(type==='task')renderTaskModal(obj);" in DASHBOARD_HTML
    assert "else if(type==='memory')renderMemoryModal(obj);" in DASHBOARD_HTML
    assert "else if(type==='incident')renderIncidentModal(obj);" in DASHBOARD_HTML
    assert "else if(type==='doctor')renderDoctorModal(obj);" in DASHBOARD_HTML
    assert "else if(type==='project')renderProjectModal(obj);" in DASHBOARD_HTML
    assert "else if(type==='code_intel')renderCodeIntelModal(obj,defaultTitle);" in DASHBOARD_HTML


def test_dashboard_buttons_rewired_to_custom_modals() -> None:
    # Agent OS buttons rewired to custom modals
    assert "$('agentOsCreateTaskBtn')?.addEventListener('click',openCreateTaskModal);" in DASHBOARD_HTML
    assert "$('agentOsRecordMemBtn')?.addEventListener('click',openRecordMemoryModal);" in DASHBOARD_HTML
    assert "$('agentOsRecordIncBtn')?.addEventListener('click',openRecordIncidentModal);" in DASHBOARD_HTML
    assert "$('agentOsCleanup')?.addEventListener('click',openCleanupModal);" in DASHBOARD_HTML

    # Project buttons rewired
    assert "$('regProjectBtn').onclick = openRegisterProjectModal;" in DASHBOARD_HTML
    assert "$('cleanMissingBtn').onclick = openCleanMissingModal;" in DASHBOARD_HTML
    assert "openDeleteProjectModal(root, name);" in DASHBOARD_HTML

    # Doctor and maintenance
    assert "$('doctorBtn').onclick=openDoctorModal;" in DASHBOARD_HTML
    assert "'db_opt'" in DASHBOARD_HTML
    assert "'cache_purge'" in DASHBOARD_HTML

    # Architecture graph node click handler
    assert "openArchNodeModal(nd)" in DASHBOARD_HTML


def test_dashboard_new_table_custom_modals_defined() -> None:
    expected_new_renderers = [
        "function renderHttpTailModal(",
        "function renderExecutionProfileModal(",
        "function renderModelStatModal(",
        "function renderCacheLayerModal(",
        "function renderAgentStatModal(",
        "function renderRouteStatModal(",
        "function renderBlockedReasonModal(",
        "function renderDeadCodeModal(",
        "function renderAuditVulnModal(",
        "function renderArchEdgeModal(",
        "function renderSchedulerJobModal(",
        "function renderHttpRequestModal(",
    ]
    for fn in expected_new_renderers:
        assert fn in DASHBOARD_HTML, f"Expected renderer function {fn} missing from DASHBOARD_HTML"


def test_dashboard_table_click_resilience_and_persistence() -> None:
    # Verify dataStore is NOT cleared inside periodic render(s)
    # Finding the render(s) function body
    render_idx = DASHBOARD_HTML.find("function render(s){")
    assert render_idx != -1
    render_body = DASHBOARD_HTML[render_idx:render_idx+200]
    assert "dataStore.clear()" not in render_body, "dataStore.clear() must not be called inside periodic render(s)"

    # Verify fallback lookup by data-id exists in global click listener
    assert "tr.dataset.id" in DASHBOARD_HTML
    assert "agentOsTasks.find" in DASHBOARD_HTML
    assert "agentOsMemories.find" in DASHBOARD_HTML
    assert "agentOsIncidents.find" in DASHBOARD_HTML

    # Verify explicit entity types and IDs are passed to clickableRow
    assert "'task',t.task_id" in DASHBOARD_HTML
    assert "'memory',(m.scope||'task')+':'+m.key" in DASHBOARD_HTML
    assert "'incident',i.incident_id" in DASHBOARD_HTML
    assert "'lease',l.lease_id" in DASHBOARD_HTML
    assert "'project',x.root" in DASHBOARD_HTML
    assert "'http_tail'" in DASHBOARD_HTML
    assert "'execution_profile'" in DASHBOARD_HTML
    assert "'model_stat'" in DASHBOARD_HTML
    assert "'cache_layer'" in DASHBOARD_HTML
    assert "'agent_stat'" in DASHBOARD_HTML
    assert "'route_stat'" in DASHBOARD_HTML
    assert "'blocked_reason'" in DASHBOARD_HTML
    assert "'dead_code'" in DASHBOARD_HTML
    assert "'audit_vulnerability'" in DASHBOARD_HTML
    assert "'arch_edge'" in DASHBOARD_HTML
    assert "'scheduler_job'" in DASHBOARD_HTML
    assert "'http_request'" in DASHBOARD_HTML


def test_dashboard_modal_scrolling_and_flex_structure() -> None:
    # Ensure modal container is flex column with overflow hidden (no double scrollbars)
    assert "display:flex;flex-direction:column;background:#0e1522" in DASHBOARD_HTML
    assert "padding:0;overflow:hidden" in DASHBOARD_HTML

    # Ensure #modalBody is the single dedicated scroll container with min-height: 0
    assert "#modalBody{flex:1 1 auto;min-height:0;overflow-y:auto" in DASHBOARD_HTML

    # Ensure cards and actions bars do not flex-shrink and squish their content
    assert ".modal-card{flex-shrink:0" in DASHBOARD_HTML
    assert ".modal-card,.modal-actions-bar,.raw-json,.modal-form,.modal-checklist{flex-shrink:0}" in DASHBOARD_HTML

    # Ensure openModal resets modalBody scroll to top
    assert "$('modalBody').scrollTop=0" in DASHBOARD_HTML


def test_dashboard_onclick_handlers_use_safe_escaping() -> None:
    # Verify escJs helper is defined
    assert "escJs=v=>esc(JSON.stringify(v))" in DASHBOARD_HTML

    # Ensure no onclick handlers interpolate raw '${esc(...)}' which breaks on Windows paths or quotes
    unsafe_single = re.findall(r'onclick=[\'"][^\'"]*\'\$\{esc\([^\)]+\)\}\'[^\'"]*[\'"]', DASHBOARD_HTML)
    assert not unsafe_single, f"Found unsafe single-quoted esc() in onclick: {unsafe_single}"

    unsafe_double = re.findall(r'onclick=[\'"][^\'"]*\"\$\{esc\([^\)]+\)\}\"[^\'"]*[\'"]', DASHBOARD_HTML)
    assert not unsafe_double, f"Found unsafe double-quoted esc() in onclick: {unsafe_double}"

    # Verify unregister modal uses safe confirmDeleteProject binding
    assert "id=\"confirmDeleteProjectBtn\"" in DASHBOARD_HTML
    assert "confirmDeleteProject(${escJs(root)})" in DASHBOARD_HTML
    assert "confirmBtn.onclick=()=>confirmDeleteProject(root)" in DASHBOARD_HTML
