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
    assert "Universal request summary" in source
    assert source.index("Universal request summary") < source.index("role=\"tablist\"")
    assert "Input unavailable for this request type" in source
    assert "Output unavailable for this request type" in source
    assert "Response unavailable for this request type" in source
    assert "Trace data availability" in source
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
    assert "trace-primary-grid" in detail_source
    assert "trace-optional-details" in detail_source
    assert "traceFirstRecorded(events,['prompt'" in model_source
    assert "traceFirstRecorded(events,['output'" in model_source


def test_trace_inspector_has_model_chat_renderer_contract_and_two_column_layout() -> None:
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
        "No model input captured",
        "No model output captured",
        "traceSanitizeValue",
        "esc(",
        "trace-chat-columns",
        "trace-chat-input",
        "trace-chat-output",
        "typeof input==='string'",
    ]:
        assert marker in source, f"Model chat renderer omits {marker}"

    css_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index(".trace-chat-columns") : DASHBOARD_HTML.index(
            "</style>", DASHBOARD_HTML.index(".trace-chat-columns")
        )
    ]
    assert "grid-template-columns" in css_source
    assert "minmax(0,1fr)" in css_source


def test_trace_inspector_has_agent_loop_tool_cards_with_bounded_safe_fields() -> None:
    assert "function renderAgentLoopPresentation(model)" in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceChatColumns(model") : DASHBOARD_HTML.index(
            "function traceDisplayModel(detail)"
        )
    ]
    for marker in [
        "Agent loop",
        "trace-chat-columns",
        "trace-tool-card",
        "trace-tool-timeline",
        "tool name",
        "arguments",
        "result",
        "error",
        "step",
        "call id",
        "traceSanitizeValue",
        "traceRawBoundValue",
        "esc(",
    ]:
        assert marker in source, f"Agent-loop renderer omits {marker}"


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
    assert "traceRawBoundValue(event,2048)" in source
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
