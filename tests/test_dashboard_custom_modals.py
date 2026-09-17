from __future__ import annotations

import re
import json
import subprocess
from shutil import which
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


def test_dashboard_display_state_helpers_defined() -> None:
    expected_helpers = [
        "function dashboardHealth(",
        "function dashboardFreshness(",
        "function redactDiagnostic(",
    ]
    for helper in expected_helpers:
        assert helper in DASHBOARD_HTML, f"Expected dashboard helper {helper} missing"


def test_dashboard_health_prioritizes_current_degradation() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function dashboardHealth(") : DASHBOARD_HTML.index(
            "function dashboardFreshness("
        )
    ]
    assert "current.degraded===true" in source
    assert "return {level:'degraded',label:'Degraded'" in source
    assert source.index("return {level:'degraded'") < source.index(
        "return {level:'attention'"
    )


def test_dashboard_freshness_normalizes_timestamp_inputs_with_explicit_now() -> None:
    freshness_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function dashboardFreshness(") : DASHBOARD_HTML.index(
            "function redactDiagnostic("
        )
    ]
    assert "function dashboardFreshness(timestamp,now=Date.now(),staleAfterMs=120000)" in freshness_source
    assert "timestamp.trim()" in freshness_source
    assert "Date.parse(timestamp||'')" in freshness_source
    assert "Timestamp unavailable" in freshness_source
    assert "Clock unavailable" in freshness_source


def test_overview_health_summary_has_alert_first_rendering_contract() -> None:
    """Missing health summary must fail before alert-first Overview exists."""
    expected_markup = [
        'id="overviewHealthSummary"',
        'id="overviewFreshness"',
        'aria-live="polite"',
    ]
    for fragment in expected_markup:
        assert fragment in DASHBOARD_HTML, f"Overview health summary missing {fragment}"

    overview_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderOverviewHealth(") : DASHBOARD_HTML.index(
            "function redactDiagnostic("
        )
    ]
    assert "dashboardHealth(snapshot)" in overview_source
    assert "dashboardFreshness(" in overview_source
    assert "Needs attention" in overview_source
    assert "switchTab(" in overview_source


def test_overview_health_uses_live_observability_and_accessible_status_contract() -> None:
    """Dropped live failure signals, receive time, or canvas summary must fail."""
    health_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function dashboardHealth(") : DASHBOARD_HTML.index(
            "function dashboardFreshness("
        )
    ]
    for signal in [
        "agent_http",
        "policy_rejection",
        "degraded_count",
        "retry_count",
        "restarts",
        "hub_online",
        "ollama_online",
    ]:
        assert signal in health_source, f"Health ignores live signal {signal}"

    overview_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderOverviewHealth(") : DASHBOARD_HTML.index(
            "function redactDiagnostic("
        )
    ]
    assert "receivedAt" in overview_source
    assert "lastOverviewAnnouncement" in overview_source
    assert "overviewAnnouncement" in DASHBOARD_HTML
    assert 'aria-live="polite"' in DASHBOARD_HTML
    assert 'id="liveChartSummary"' in DASHBOARD_HTML
    assert "aria-label" in DASHBOARD_HTML
    assert "lastOverviewReceivedAt" in DASHBOARD_HTML
    assert "renderOverviewHealth(last,lastOverviewReceivedAt)" in DASHBOARD_HTML


def test_dashboard_health_marks_stale_heartbeat_as_degraded() -> None:
    """A dead heartbeat must never render as healthy runtime state."""
    health_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function dashboardHealth(") : DASHBOARD_HTML.index(
            "function dashboardFreshness("
        )
    ]
    assert "heartbeat_stale" in health_source
    assert "heartbeatStale" in health_source
    assert "'stale'" in health_source
    stale_guard = health_source[health_source.index("if(hubOnline===false") :]
    assert "heartbeatStale" in stale_guard
    assert "return {level:'degraded'" in stale_guard


def test_dashboard_redacts_diagnostic_secrets_and_absolute_paths() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    assert "Bearer\\s+" in source
    assert "api[_-]?key" in source
    assert "(^|\\s)((?:--(?:api[-_]?key|token|secret|password)" in source
    assert "[A-Za-z]:[\\\\/]" in source
    assert "(?<![:\\w])\\/" in source


def test_dashboard_redacts_quoted_json_secret_keys() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    assert "(?:[\"'](?:api[_-]?key|token|secret|password|authorization)[\"']" in source
    assert "<redacted>" in source


def test_trace_inspector_has_universal_redacted_display_model() -> None:
    """Every retained trace needs a useful safe summary before optional detail panes."""
    assert "function traceDisplayModel(detail)" in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function renderTraceDetail(d)"
        )
    ]
    for field in [
        "identity",
        "lifecycle",
        "timing",
        "actor",
        "correlations",
        "retainedBytes",
        "input",
        "output",
        "response",
        "errors",
        "events",
        "modelExecutions",
        "toolCalls",
    ]:
        assert field in source, f"Trace display model omits {field}"
    assert "traceSanitizeValue" in source
    assert "redactDiagnostic" in source


def test_trace_inspector_classifies_stable_presentation_kinds() -> None:
    assert "function tracePresentationKind(model)" in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function tracePresentationKind(model)") : DASHBOARD_HTML.index(
            "function tracePresentationData(model)"
        )
    ]
    for kind in [
        "agent_loop",
        "model_chat",
        "command",
        "review",
        "repo_intelligence",
        "rag_search",
        "async_job",
        "request_response",
    ]:
        assert f"'{kind}'" in source
    assert source.index("if(hasModel&&hasTools)") < source.index(
        "if(hasModel)return 'model_chat'"
    )
    assert "traceRecorded(model.input)" in source
    assert "traceRecorded(model.output)" in source


def test_trace_inspector_normalizes_bounded_sanitized_presentation_data() -> None:
    assert "function traceChatTurns(events)" in DASHBOARD_HTML
    assert "function tracePresentationData(model)" in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceChatTurns(events)") : DASHBOARD_HTML.index(
            "function traceAvailability(model"
        )
    ]
    assert "chatTurns" in source
    assert "toolInteractions" in source
    assert "turns.slice(-100)" in source
    assert "traceSanitizeValue" in source
    assert "type==='tool_call'" in source
    assert "type==='tool_result'" in source
    assert "match.result=payload" in source
    assert "presentation=tracePresentationData(model)" in source


def test_trace_inspector_renders_universal_summary_before_optional_panels() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert "traceDisplayModel(d)" in source
    assert "universalSummary=traceSummary(model,unavailableCopy)" in source
    assert "${header}${universalSummary}${presentationMarkup}${optionalMarkup}" in source
    for marker in [
        "Input unavailable for this request type",
        "Output unavailable for this request type",
        "Response unavailable for this request type",
        "Trace data availability",
    ]:
        assert marker in DASHBOARD_HTML
    assert "role=\"tabpanel\"" in source
    assert "function tracePanel(" in DASHBOARD_HTML


def test_trace_inspector_prioritizes_input_output_and_demotes_technical_detail() -> None:
    detail_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    model_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "renderTracePresentation(model)" in detail_source
    assert "trace-optional-details" in detail_source
    assert "traceFirstRecorded(events,['prompt'" in model_source
    assert "traceFirstRecorded(events,['output'" in model_source


def test_trace_inspector_stacks_primary_and_model_chat_panels_full_width() -> None:
    assert ".trace-primary-grid{display:grid;grid-template-columns:1fr" in DASHBOARD_HTML
    assert ".trace-chat-columns{display:grid;grid-template-columns:1fr" in DASHBOARD_HTML
    assert ".trace-optional-details{width:100%" in DASHBOARD_HTML


def test_trace_inspector_separates_type_specific_field_labels_and_values() -> None:
    assert ".trace-presentation-field{display:grid" in DASHBOARD_HTML
    assert "grid-template-columns:minmax(150px,220px) minmax(0,1fr)" in DASHBOARD_HTML
    assert ".trace-command-top{border:" in DASHBOARD_HTML


def test_trace_inspector_formats_generic_model_objects_without_object_coercion() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function promptText(value)") : DASHBOARD_HTML.index(
            "function promptBlock(text"
        )
    ]
    script = source + "console.log(promptText({answer:'structured'}));"
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert "structured" in result.stdout
    assert "[object Object]" not in result.stdout


def test_trace_inspector_dispatches_primary_body_before_optional_technical_details() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert "const presentationMarkup=renderTracePresentation(model);" in source
    assert "const optionalMarkup=`<details class=\"trace-optional-details\"" in source
    assert source.index("renderTracePresentation(model)") < source.index(
        "const optionalMarkup="
    )
    assert "${header}${universalSummary}${presentationMarkup}${optionalMarkup}" in source
    assert "const primaryMarkup=" not in source


def test_trace_inspector_keeps_tabs_and_raw_fallback_inside_optional_details() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    optional_start = source.index("const optionalMarkup=")
    optional_end = source.index("</details>", optional_start)
    optional_source = source[optional_start:optional_end]
    assert '<nav class="trace-tabs" role="tablist" aria-label="Trace views">' in optional_source
    assert "panelMarkup" in optional_source
    assert "tracePanel('raw'" not in source[optional_start:]


def test_trace_inspector_polling_guards_stale_responses_and_bounds_client_buffer() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("async function openTrace(") : DASHBOARD_HTML.index(
            "function openModal("
        )
    ]
    for marker in [
        "tracePollGeneration",
        "tracePollInFlight",
        "pollGeneration=++tracePollGeneration",
        "tracePollInFlight=pollGeneration",
        "tracePollInFlight=false",
        "traceAppendEvents(traceEvents,d.events",
        "pollGeneration!==tracePollGeneration",
        "pollTraceId!==activeTraceId",
    ]:
        assert marker in source, f"Polling guard missing: {marker}"


def test_trace_inspector_accepts_only_finite_numeric_next_sequence() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("async function openTrace(") : DASHBOARD_HTML.index(
            "function openModal("
        )
    ]
    assert "traceSeq=traceFiniteSequence(d.next_seq,traceSeq)" in source


def test_trace_inspector_removes_unreachable_summary_panel_branch() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert "panel.id==='summary'" not in source


def test_trace_sequence_runtime_retains_prior_value_for_malformed_next_sequence() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceFiniteSequence(") : DASHBOARD_HTML.index(
            "function traceBoundedEvents("
        )
    ]
    script = (
        source
        + "console.log(JSON.stringify([traceFiniteSequence(4,2),traceFiniteSequence(null,2),"
        + "traceFiniteSequence('5',2),traceFiniteSequence(NaN,2),traceFiniteSequence(1,2)]));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [4, 2, 2, 2, 2]


def test_trace_presentation_kind_prioritizes_explicit_specialized_requests() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function tracePresentationKind(model)") : DASHBOARD_HTML.index(
            "function tracePresentationData(model)"
        )
    ]
    script = (
        "const traceRecorded=v=>v!==null&&v!==undefined&&(typeof v!=='object'||Object.keys(v).length>0);"
        + source
        + "const base={modelExecutions:[{}],input:{prompt:'x'},output:'y',toolCalls:[{}],events:[]};"
        + "console.log(JSON.stringify(["
        + "tracePresentationKind({...base,identity:{action:'/api/command'}}),"
        + "tracePresentationKind({...base,identity:{action:'/api/review'}}),"
        + "tracePresentationKind({...base,session:{kind:'async_job'}})"
        + "]));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == ["command", "review", "async_job"]


def test_trace_thinking_details_have_stable_keys_and_restore_across_renders() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert "captureTraceThinkingDetails" in source
    assert "restoreTraceThinkingDetails" in source
    assert "data-thinking-key" in DASHBOARD_HTML
    assert "thinkingDetailsOpen" in source


def test_trace_event_append_deduplicates_sequence_ids() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("const traceEventBufferLimit=") : DASHBOARD_HTML.index(
            "function traceBoundedEvents("
        )
    ]
    script = (
        source
        + "console.log(JSON.stringify(traceAppendEvents([{seq:1},{seq:2}],[{seq:2},{seq:3}],4)));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["events"] == [{"seq": 1}, {"seq": 2}, {"seq": 3}]


def test_trace_inspector_keeps_optional_details_open_and_summary_visible() -> None:
    detail_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    model_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "traceOptionalDetailsOpen" in detail_source
    assert "existingOptionalDetails.open" in detail_source
    assert "traceOptionalDetailsOpen?' open':''" in detail_source
    assert "${header}${universalSummary}${presentationMarkup}${optionalMarkup}" in detail_source
    assert "${universalSummary}<nav" not in detail_source
    assert "tracePanel('summary'" not in model_source


def test_trace_event_buffer_runtime_caps_events_and_preserves_server_total() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("const traceEventBufferLimit=") : DASHBOARD_HTML.index(
            "function traceBoundedEvents("
        )
    ]
    script = (
        source
        + "const current=Array.from({length:200},(_,i)=>({seq:i}));"
        + "const incoming=Array.from({length:25},(_,i)=>({seq:200+i}));"
        + "console.log(JSON.stringify(traceAppendEvents(current,incoming,900)));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    bounded = json.loads(result.stdout)
    assert len(bounded["events"]) == 200
    assert bounded["events"][-1]["seq"] == 224
    assert bounded["eventsTotal"] == 900


def test_trace_inspector_has_model_chat_renderer_contract_and_codex_timeline() -> None:
    assert "function renderModelChatPresentation(model)" in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function tracePresentationValue(value") : DASHBOARD_HTML.index(
            "function traceDisplayModel(detail)"
        )
    ]
    for marker in [
        "Model chat",
        "Model input",
        "Model output",
        "model name",
        "step",
        "role",
        "No model output captured",
        "traceSanitizeValue",
        "esc(",
        "trace-codex-timeline",
        "trace-timeline-event",
        "trace-thinking",
        "<details",
        "tool call",
        "tool result",
        "assistant",
        "typeof input==='string'",
    ]:
        assert marker in source, f"Model chat renderer omits {marker}"

    css_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index(".trace-chat-columns") : DASHBOARD_HTML.index(
            "</style>", DASHBOARD_HTML.index(".trace-chat-columns")
        )
    ]
    assert "trace-tool-timeline" in css_source
    assert "trace-tool-card" in css_source


def test_trace_inspector_has_agent_loop_tool_cards_with_bounded_safe_fields() -> None:
    assert "function renderAgentLoopPresentation(model)" in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceChatColumns(model") : DASHBOARD_HTML.index(
            "function traceDisplayModel(detail)"
        )
    ]
    for marker in [
        "Agent loop",
        "trace-codex-timeline",
        "trace-tool-card",
        "trace-tool-timeline",
        "tool name",
        "arguments",
        "result",
        "error",
        "step",
        "call id",
        "tool call",
        "tool result",
        "traceSanitizeValue",
        "traceRawBoundValue",
        "esc(",
    ]:
        assert marker in source, f"Agent-loop renderer omits {marker}"


def test_trace_inspector_has_request_specific_renderer_contracts() -> None:
    source = _trace_presentation_runtime_source()
    contracts = {
        "renderCommandPresentation(model)": [
            "command",
            "args",
            "input",
            "stdout",
            "stderr",
            "exit code",
            "retries",
            "duration",
        ],
        "renderReviewPresentation(model)": [
            "request",
            "context",
            "diff",
            "findings",
            "recommendation",
            "status",
        ],
        "renderRepoIntelligencePresentation(model)": [
            "repository",
            "root",
            "operation",
            "query",
            "files",
            "symbols",
            "context",
            "result",
        ],
        "renderRagSearchPresentation(model)": [
            "query",
            "sources",
            "results",
            "score",
            "provider",
            "answer",
            "truncation",
        ],
        "renderAsyncJobPresentation(model)": [
            "lifecycle",
            "status",
            "queue wait",
            "retries",
            "worker input",
            "result",
            "error",
            "job id",
            "correlation",
        ],
        "renderRequestResponsePresentation(model)": [
            "request",
            "input",
            "response",
            "output",
            "status",
            "timing",
            "error",
            "No request captured",
            "No response captured",
        ],
    }
    for function, markers in contracts.items():
        assert f"function {function}" in source
        renderer = source[source.index(f"function {function}") :]
        for marker in markers:
            assert marker in renderer, f"{function} omits {marker}"
    assert "tracePresentationValue" in source
    assert "traceBudgetMarkup" in source
    assert "traceFinalizeMarkup" in source
    assert "traceSanitizeValue" in source
    assert "renderCommandPresentation(model)" in source
    assert "renderReviewPresentation(model)" in source
    assert "renderRepoIntelligencePresentation(model)" in source
    assert "renderRagSearchPresentation(model)" in source
    assert "renderAsyncJobPresentation(model)" in source
    assert "renderRequestResponsePresentation(model)" in source


def test_trace_inspector_dispatches_request_specific_renderers() -> None:
    source = _trace_presentation_runtime_source()
    dispatcher = source[source.index("function renderTracePresentation(model)") :]
    for kind, renderer in [
        ("command", "renderCommandPresentation"),
        ("review", "renderReviewPresentation"),
        ("repo_intelligence", "renderRepoIntelligencePresentation"),
        ("rag_search", "renderRagSearchPresentation"),
        ("async_job", "renderAsyncJobPresentation"),
        ("request_response", "renderRequestResponsePresentation"),
    ]:
        assert f"kind==='{kind}'" in dispatcher
        assert f"{renderer}(model)" in dispatcher


def test_trace_request_renderers_expose_reviewer_gap_contracts() -> None:
    source = _trace_presentation_runtime_source()
    for marker in [
        "severity counts",
        "critical",
        "high",
        "medium",
        "low",
        "Command and arguments",
        "trace-command-top",
        "rank",
        "score",
        "provider",
        "trace-rag-ranked",
        "trace-rag-source-details",
        "traceMergeRecorded",
    ]:
        assert marker in source, f"Reviewer gap marker missing: {marker}"


def test_trace_presentation_data_merges_sibling_event_fields() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "identity": {"action": "/api/command"},
        "session": {"kind": "request"},
        "events": [
            {"payload": {"command": "pytest"}},
            {"payload": {"args": ["-q"], "stdout": "ok"}},
            {"payload": {"stderr": "", "exit_code": 0, "duration_ms": 12}},
            {"payload": {"diff": "patch", "findings": [{"severity": "high"}]}},
            {"payload": {"recommendation": "fix", "result": {"value": "kept"}}},
        ],
    }
    script = (
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;let traceOpenSteps=new Set();"
        + source
        + f"console.log(JSON.stringify(tracePresentationData({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    presentation = json.loads(result.stdout)
    command = presentation["command"]
    for key in ["command", "args", "stdout", "stderr", "exit_code", "duration_ms"]:
        assert key in command
    review = presentation["review"]
    for key in ["diff", "findings", "recommendation"]:
        assert key in review


def test_trace_request_renderers_runtime_show_severity_command_and_ranked_rag() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "review": {
            "findings": [
                {"severity": "critical", "message": "bad"},
                {"severity": "high", "message": "warn"},
            ],
            "recommendation": "fix",
        },
        "command": {
            "command": "pytest",
            "args": ["-q"],
            "stdout": "ok",
            "stderr": "none",
            "exit_code": 0,
            "retries": 1,
            "duration_ms": 12,
        },
        "retrieval": {
            "query": "trace",
            "sources": [
                {"score": 0.2, "provider": "low", "content": "small"},
                {"score": 0.9, "provider": "high", "content": "x" * 5000},
            ],
            "answer": "answer",
        },
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const m={{presentation:{json.dumps(fixture)},lifecycle:{{}},correlations:{{}},session:{{}},identity:{{}}}};"
        + "console.log(JSON.stringify({review:renderReviewPresentation(m),command:renderCommandPresentation(m),rag:renderRagSearchPresentation(m)}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = json.loads(result.stdout)
    assert "severity counts" in rendered["review"].lower()
    assert "critical" in rendered["review"].lower()
    assert "Command and arguments" in rendered["command"]
    assert "stdout" in rendered["command"] and "stderr" in rendered["command"]
    assert "rank" in rendered["rag"].lower() and "score" in rendered["rag"].lower()
    assert "<details" in rendered["rag"]
    assert "answer" in rendered["rag"]


def test_trace_timeline_runtime_tolerates_malformed_events_and_caps_cumulative_payload() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    events = [None, "bad event", {"event_type": "tool_call", "payload": "bad payload"}]
    events.extend(
        {"event_type": "event", "payload": {f"field_{i}": "x" * 300}}
        for i in range(140)
    )
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;let traceOpenSteps=new Set();"
        + source
        + f"const events={json.dumps(events)};"
        + "const compact=compactTimelineEvents(events);const timeline=traceTimeline(events);const bounded=traceBoundedEvents(events);"
        + "console.log(JSON.stringify({compact:compact.length,timeline:timeline.length,bounded:JSON.stringify(bounded.events).length}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    assert output["compact"] > 0
    assert output["timeline"] > 0
    assert output["bounded"] <= 26000


def test_trace_bounded_events_uses_one_shared_budget_for_wide_deep_events() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceBoundedEvents(") : DASHBOARD_HTML.index(
            "function traceDisplaySession("
        )
    ]
    assert "traceRawBoundValue(traceRawBoundValue" not in source
    assert "traceRawBoundValue(event,2048,0,budget)" in source
    assert "remaining:24000" in source
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    wide = {f"wide_{i}": {f"deep_{j}": "x" * 500 for j in range(20)} for i in range(80)}
    script = (
        source
        + f"const bounded=traceBoundedEvents([{{event_type:'wide',payload:{json.dumps(wide)}}}]);"
        + "console.log(JSON.stringify(bounded));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    bounded = json.loads(result.stdout)
    assert len(json.dumps(bounded["events"])) <= 26000
    assert bounded["eventsTruncated"] is True


def test_trace_presentation_runtime_coerces_non_array_events_to_empty() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    models = [
        {"events": "not events", "session": {}, "identity": {}},
        {"events": {"event_type": "bad"}, "session": {}, "identity": {}},
    ]
    models_json = json.dumps(models)
    script = (
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const models={models_json};console.log(JSON.stringify(models.map(tracePresentationData)));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    presentations = json.loads(result.stdout)
    assert [presentation["chatTurns"] for presentation in presentations] == [[], []]
    assert [presentation.get("command") for presentation in presentations] == [None, None]


def test_trace_review_severity_runtime_merges_counts_map_and_findings() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "review": {
                "severity_counts": {"critical": 2, "high": 1, "medium": 3, "low": 4},
                "findings": [{"severity": "critical"}, {"severity": "low"}],
            }
        },
        "lifecycle": {},
        "correlations": {},
        "session": {},
        "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderReviewPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    html = json.loads(result.stdout)
    for marker in ["critical: 2", "high: 1", "medium: 3", "low: 4"]:
        assert marker in html


def test_trace_rag_runtime_sorts_finite_scores_before_stable_unscored_items() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "retrieval": {
                "query": "q",
                "sources": [
                    {"provider": "unscored-a", "score": "bad"},
                    {"provider": "finite-low", "score": 0.2},
                    {"provider": "unscored-b"},
                    {"provider": "finite-high", "score": 0.9},
                ],
                "answer": "a",
            }
        },
        "lifecycle": {},
        "correlations": {},
        "session": {},
        "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderRagSearchPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    html = json.loads(result.stdout)
    assert html.index("finite-high") < html.index("finite-low")
    assert html.index("unscored-a") < html.index("unscored-b")
    assert html.index("finite-low") < html.index("unscored-a")


def test_trace_inspector_shows_model_prompt_as_input() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "prompt" in source
    assert "model_request" in source


def test_trace_inspector_prefers_full_model_payload_over_api_request_wrapper() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "const modelInput=traceFirstRecorded(events,['prompt','messages','content','input','arguments','args','query'])" in source
    assert "traceRecorded(modelInput)?modelInput" in source
    assert "traceRecorded(effectivePayload)?effectivePayload" in source


def test_trace_inspector_uses_accessible_conditional_tabs_and_safe_trace_values() -> None:
    tab_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceTab(") : DASHBOARD_HTML.index(
            "function traceStatus("
        )
    ]
    assert 'role="tab"' in tab_source
    assert "aria-controls" in tab_source
    detail_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert "model.panels.filter(panel=>panel.available)" in detail_source
    assert "traceSanitizeValue" in detail_source
    assert "panelMarkup" in detail_source
    assert "hidden" in detail_source
    assert "panel.id===traceView" in detail_source
    model_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "tracePanel('events','Events',()=>traceEventList(events)" in model_source
    assert "tracePanel('raw','Raw',()=>traceRaw" in model_source
    assert "events.slice(-100)" in model_source


def _trace_presentation_runtime_source() -> str:
    return DASHBOARD_HTML[
        DASHBOARD_HTML.index("const humanLabel=") : DASHBOARD_HTML.index(
            "function traceDisplayModel(detail)"
        )
    ]


def test_trace_agent_loop_runtime_renders_nested_tool_errors_and_successes() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "kind": "agent_loop",
            "chatTurns": [
                {
                    "step": 3,
                    "input": {"messages": [{"role": "user", "content": "run"}]},
                    "output": "done",
                    "tools": [
                        {
                            "call": {"call_id": "bad-1", "name": "shell", "arguments": {"cmd": "false"}},
                            "result": {"call_id": "bad-1", "result": {"error": "<failure>"}},
                        },
                        {
                            "call": {"call_id": "ok-1", "name": "read", "arguments": {"path": "x"}},
                            "result": {"call_id": "ok-1", "result": {"value": "success"}},
                        },
                    ],
                }
            ],
            "modelInput": {"messages": [{"role": "user", "content": "run"}]},
            "modelOutput": "done",
        },
        "session": {"model": "fixture-model"},
        "actor": {},
        "correlations": {},
        "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'').replace(/secret/gi,'<redacted>');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderAgentLoopPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    html = json.loads(result.stdout)
    assert "error" in html
    assert "&lt;failure&gt;" in html
    assert "success" in html
    assert "bad-1" in html and "ok-1" in html


def test_trace_model_chat_runtime_renders_one_chronological_codex_timeline() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {"kind": "agent_loop", "chatTurns": [], "modelInput": {"messages": [{"role": "user", "content": "run"}]}, "modelOutput": "done"},
        "events": [
            {"seq": 1, "event_type": "model_request", "payload": {"step": 1, "messages": [{"role": "user", "content": "run"}], "model": "m"}},
            {"seq": 2, "event_type": "assistant_thinking", "payload": {"step": 1, "content": "reason"}},
            {"seq": 3, "event_type": "tool_call", "payload": {"step": 1, "call_id": "c1", "name": "shell", "arguments": {"cmd": "pwd"}}},
            {"seq": 4, "event_type": "tool_result", "payload": {"step": 1, "call_id": "c1", "result": {"error": "failed"}}},
            {"seq": 5, "event_type": "output_delta", "payload": {"step": 1, "text": "done"}},
            {"seq": 6, "event_type": "turn_end", "payload": {"step": 1}},
        ],
        "session": {"model": "m"}, "actor": {}, "correlations": {}, "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'').replace(/secret/gi,'<redacted>');} let traceRevealRedactedDetails=false;"
        + source + f"console.log(JSON.stringify(renderAgentLoopPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    markers = ["Model input", "Thinking", "Tool call", "Tool result", "Assistant output", "Turn boundary"]
    assert [html.index(marker) for marker in markers] == sorted(html.index(marker) for marker in markers)
    assert '<details class="trace-thinking"' in html
    assert "run" in html and "failed" in html and "c1" in html


def test_trace_model_chat_runtime_has_clear_empty_timeline_state() -> None:
    source = _trace_presentation_runtime_source()
    fixture = {"presentation": {"kind": "model_chat", "chatTurns": [], "modelInput": None, "modelOutput": None}, "session": {}, "actor": {}, "correlations": {}, "identity": {}}
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;" + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "No model events captured" in html


def test_trace_tool_result_card_carries_matching_call_context() -> None:
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {"kind": "model_chat", "modelOutput": "done"},
        "events": [
            {"seq": 1, "event_type": "tool_call", "payload": {"step": 4, "call_id": "call-4", "name": "shell", "arguments": {"cmd": "false"}}},
            {"seq": 2, "event_type": "tool_result", "payload": {"step": 4, "call_id": "call-4", "result": {"error": "failed"}}},
        ],
        "session": {}, "actor": {}, "correlations": {}, "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;" + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    result_card = html[html.index("Tool result") :]
    assert "shell" in result_card
    assert "call-4" in result_card
    assert "step 4" in result_card
    assert "Cmd" in result_card or "cmd" in result_card
    assert "failed" in result_card


def test_trace_codex_timeline_appends_missing_final_assistant_output_once() -> None:
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {"kind": "model_chat", "modelOutput": "final answer"},
        "events": [{"seq": 1, "event_type": "model_request", "payload": {"messages": [{"role": "user", "content": "question"}]}}],
        "session": {"output": "session answer"}, "actor": {}, "correlations": {}, "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;" + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert html.count("Assistant output") == 1
    assert "final answer" in html


def test_trace_codex_timeline_keeps_terminal_output_after_partial_stream() -> None:
    source = _trace_presentation_runtime_source()
    fixture = {"presentation": {"kind": "model_chat", "modelOutput": "partial plus final"}, "events": [{"seq": 1, "event_type": "output_delta", "payload": {"text": "partial"}}], "session": {"output": "partial plus final"}, "actor": {}, "correlations": {}, "identity": {}}
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;" + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "partial plus final" in html
    assert html.count("Assistant output") == 2


def test_trace_codex_timeline_retains_synthetic_final_after_event_cap() -> None:
    source = _trace_presentation_runtime_source()
    events = [{"seq": 1, "event_type": "assistant_output", "payload": {"content": "terminal answer"}}]
    events.extend({"seq": index, "event_type": "turn_end", "payload": {"step": index}} for index in range(2, 112))
    fixture = {"presentation": {"kind": "model_chat"}, "events": events, "session": {"output": "terminal answer"}, "actor": {}, "correlations": {}, "identity": {}}
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;" + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "terminal answer" in html
    assert "Assistant output" in html


def test_trace_malformed_non_object_event_payload_stays_visible() -> None:
    source = _trace_presentation_runtime_source()
    fixture = {"presentation": {"kind": "model_chat"}, "events": [{"seq": 1, "event_type": "event", "payload": "broken-payload"}], "session": {}, "actor": {}, "correlations": {}, "identity": {}}
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;" + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "Malformed event payload" in html
    assert "broken-payload" in html


def test_trace_inspector_preserves_outer_technical_details_and_contains_timeline() -> None:
    source = DASHBOARD_HTML[DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index("function setTraceView(view)")]
    assert "#traceTechnicalDetails" in source
    assert 'id="traceTechnicalDetails"' in source
    assert "overflow-wrap:anywhere" in DASHBOARD_HTML
    assert "word-break:break-word" in DASHBOARD_HTML


def test_trace_model_chat_runtime_keeps_request_envelope_visible_and_bounded() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "kind": "model_chat",
            "chatTurns": [],
            "modelInput": {
                "model": "fixture-model",
                "stream": True,
                "options": {"temperature": 0.2, "token": "secret"},
                "request": {"request_id": "req-1", "path": "/chat"},
                "messages": [
                    {"role": "system", "content": "system <safe>"},
                    {"role": "developer", "content": "developer"},
                    {"role": "user", "content": "user"},
                ],
                "content": "fallback content",
                "prompt": "fallback prompt " + ("x" * 13000),
            },
            "modelOutput": "",
            "requestEnvelope": {"headers": {"x-request": "kept"}},
        },
        "session": {"model": "fixture-model"},
        "actor": {},
        "correlations": {},
        "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'').replace(/secret/gi,'<redacted>');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    html = json.loads(result.stdout)
    for value in ["fixture-model", "stream", "Options", "request_id", "system", "developer", "user"]:
        assert value.lower() in html.lower()
    assert "system &lt;safe&gt;" in html
    assert "secret" not in html
    assert "No model output captured" in html


def test_trace_model_chat_runtime_redacts_cookie_headers_and_private_key_fields() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    redact = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    fixture = {
        "presentation": {
            "kind": "model_chat",
            "chatTurns": [],
            "modelInput": {
                "headers": {
                    "cookie": "session=cookie-secret",
                    "set-cookie": "session=set-cookie-secret",
                    "private-key": "private-key-secret",
                },
                "messages": [{"role": "user", "content": "safe"}],
            },
            "modelOutput": "ok",
        },
        "session": {"model": "fixture-model"},
        "actor": {},
        "correlations": {},
        "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        + redact
        + "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    html = json.loads(result.stdout)
    for secret in ["cookie-secret", "set-cookie-secret", "private-key-secret"]:
        assert secret not in html
    assert "redacted" in html.lower()


def test_trace_model_chat_runtime_enforces_cumulative_payload_budget() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    redact = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    oversized = {f"oversized_key_{index}": "x" * 180 for index in range(240)}
    oversized["messages"] = [{"role": "user", "content": "y" * 18000}]
    fixture = {
        "presentation": {
            "kind": "model_chat",
            "chatTurns": [],
            "modelInput": oversized,
            "modelOutput": "ok",
        },
        "session": {"model": "fixture-model"},
        "actor": {},
        "correlations": {},
        "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        + redact
        + "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    html = json.loads(result.stdout)
    assert "payload budget" in html.lower()
    assert "oversized_key_239" not in html


def test_trace_model_chat_runtime_caps_final_html_across_repeated_large_messages() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    redact = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    large = "message-payload-" + ("z" * 4800)
    fixture = {
        "presentation": {
            "kind": "model_chat",
            "chatTurns": [
                {"step": index + 1, "input": {"messages": [{"role": "user", "content": large}]}, "output": large}
                for index in range(10)
            ],
            "modelInput": {"messages": [{"role": "user", "content": large}]},
            "modelOutput": large,
        },
        "session": {"model": "fixture-model"},
        "actor": {},
        "correlations": {},
        "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        + redact
        + "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    html = json.loads(result.stdout)
    assert len(html) <= 24000
    assert "payload budget" in html.lower()


def test_trace_model_chat_runtime_redacts_embedded_pem_certificate_and_ssh_keys() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    redact = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    embedded = '{"pem":"pem-secret","certificate":"certificate-secret","ssh-key":"ssh-secret","cookie":"cookie-secret","private-key":"private-secret"}'
    fixture = {
        "presentation": {
            "kind": "model_chat",
            "chatTurns": [],
            "modelInput": {"metadata": embedded, "messages": [{"role": "user", "content": "safe"}]},
            "modelOutput": "ok",
        },
        "session": {"model": "fixture-model"},
        "actor": {},
        "correlations": {},
        "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        + redact
        + "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    html = json.loads(result.stdout)
    for secret in ["pem-secret", "certificate-secret", "ssh-secret", "cookie-secret", "private-secret"]:
        assert secret not in html
    assert "redacted" in html.lower()


def test_trace_raw_projection_bounds_events_before_sanitization() -> None:
    bounded_events_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceBoundedEvents(") : DASHBOARD_HTML.index(
            "function traceRawBoundValue("
        )
    ]
    assert "list.slice(-eventLimit)" in bounded_events_source
    projection_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceRawProjection(") : DASHBOARD_HTML.index(
            "function traceRaw("
        )
    ]
    assert "traceBoundedEvents(detail?.events,eventLimit)" in projection_source
    assert "events_total" in projection_source
    assert "events_truncated" in projection_source
    model_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "traceRaw(traceRawProjection(detail))" in model_source


def test_trace_display_model_bounds_events_and_raw_fields_before_sanitization() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "traceBoundedEvents(rawEvents)" in source
    assert "traceSanitizeValue(rawEventProjection.events)" in source
    assert "eventsTotal" in source
    projection_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceRawBoundValue(") : DASHBOARD_HTML.index(
            "function traceRaw("
        )
    ]
    assert "value.slice(0,limit)" in projection_source
    assert "traceRawBoundValue(rawSession.request)" in projection_source


def test_bounded_trace_events_retain_request_metadata_and_cap_each_event() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceBoundedEvents(") : DASHBOARD_HTML.index(
            "function traceDisplaySession("
        )
    ]
    assert "event_type==='request_received'" in source
    assert "traceRawBoundValue(event,2048,0,budget)" in source
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    script = (
        source
        + "const events=[{event_type:'request_received',payload:{method:'POST',path:'/api/reason'}}]"
        + ".concat(Array.from({length:101},(_,index)=>({event_type:'output_delta',payload:{text:String(index)}})));"
        + "const bounded=traceBoundedEvents(events);console.log(JSON.stringify(bounded));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    bounded = json.loads(result.stdout)
    assert bounded["eventsTotal"] == 102
    assert any(event["event_type"] == "request_received" for event in bounded["events"])


def test_trace_display_model_derives_http_identity_and_keeps_effective_payload() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "event?.event_type==='request_received'" in source
    assert "requestReceived?.payload" in source
    assert "requestPayload.method" in source
    assert "requestPayload.path" in source
    assert "requestPayload.request_id" in source
    assert "session.effective_payload" in source
    assert "effectivePayload" in source


def test_trace_inspector_has_keyboard_roving_tabs_and_explicit_reveal_control() -> None:
    assert "function moveTraceTab(" in DASHBOARD_HTML
    keyboard_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function moveTraceTab(") : DASHBOARD_HTML.index(
            "async function openTrace("
        )
    ]
    for key in ["ArrowLeft", "ArrowRight", "Home", "End"]:
        assert key in keyboard_source
    assert "requestAnimationFrame" in keyboard_source
    assert "traceRevealRedactedDetails=false" in DASHBOARD_HTML
    assert "data-trace-reveal" in DASHBOARD_HTML
    assert 'aria-pressed="${traceRevealRedactedDetails}"' in DASHBOARD_HTML
    assert "toggleTraceReveal" in DASHBOARD_HTML


def test_trace_sanitizer_redacts_sensitive_object_values_by_key() -> None:
    """Default inspector rendering must not expose values hidden behind sensitive keys."""
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    redact = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    sanitizer = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceSensitiveField(") : DASHBOARD_HTML.index(
            "function traceRecorded("
        )
    ]
    fixture = {
        "api_key": "api-secret",
        "authorization": "Bearer authorization-secret",
        "nested": {"token": "token-secret", "safe": "kept"},
    }
    script = f"let traceRevealRedactedDetails=false;{redact}{sanitizer}console.log(JSON.stringify(traceSanitizeValue({json.dumps(fixture)})));"
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    sanitized = json.loads(result.stdout)
    assert sanitized["api_key"] == "<redacted>"
    assert sanitized["authorization"] == "<redacted>"
    assert sanitized["nested"]["token"] == "<redacted>"
    assert sanitized["nested"]["safe"] == "kept"
