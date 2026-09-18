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


def test_trace_sanitizer_keeps_reused_values_but_marks_true_cycles() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=true;"
        + source
        + "const shared={value:'visible'};"
        + "const repeated={first:shared,second:shared};"
        + "const cyclic={value:'visible'};cyclic.self=cyclic;"
        + "console.log(JSON.stringify({repeated:traceSanitizeValue(repeated),cyclic:traceSanitizeValue(cyclic)}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    sanitized = json.loads(result.stdout)
    assert sanitized["repeated"]["first"]["value"] == "visible"
    assert sanitized["repeated"]["second"]["value"] == "visible"
    assert sanitized["cyclic"]["self"] == "<cycle omitted>"


def test_trace_sanitizer_redacts_nested_sensitive_key_variants_in_primary_output() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    secrets = {
        "api_key_id": "API_KEY_ID_SECRET",
        "secret_key": "SECRET_KEY_SECRET",
        "token_value": "TOKEN_VALUE_SECRET",
        "x-api-key": "X_API_KEY_SECRET",
        "authorization_header": "AUTHORIZATION_SECRET",
        "password_hash": "PASSWORD_SECRET",
        "clientSecret": "CLIENT_SECRET_SECRET",
        "nested": {"Access-Token-Id": "ACCESS_TOKEN_SECRET"},
    }
    fixture = {
        "presentation": {
            "kind": "command",
            "command": {
                "command": "pytest",
                "args": [secrets],
                "stdout": "safe command output",
            },
        }
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const fixture={json.dumps(fixture)};"
        + "const sanitized=traceSanitizeValue(fixture);"
        + "const rendered=renderTracePresentation(fixture);"
        + "console.log(JSON.stringify({sanitized,rendered}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    sanitized = json.dumps(output["sanitized"])
    rendered = output["rendered"]
    for secret in [
        "API_KEY_ID_SECRET",
        "SECRET_KEY_SECRET",
        "TOKEN_VALUE_SECRET",
        "X_API_KEY_SECRET",
        "AUTHORIZATION_SECRET",
        "PASSWORD_SECRET",
        "CLIENT_SECRET_SECRET",
        "ACCESS_TOKEN_SECRET",
    ]:
        assert secret not in sanitized
        assert secret not in rendered
    assert "<redacted>" in sanitized
    assert "safe command output" in rendered


def test_trace_inspector_renders_structured_model_content_without_object_coercion() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceReadableMarkup(") : DASHBOARD_HTML.index(
            "function traceCodexEvents(model,presentation)"
        )
    ]
    assert "function traceReadableMarkup(value,budget,limit=8000)" in source
    assert "function traceHumanReadableMarkup(value)" in DASHBOARD_HTML
    assert "safe&&typeof safe==='object'?renderAny(safe):`<pre class=\"trace-output\">${esc(traceHumanText(safe))}</pre>`" in DASHBOARD_HTML
    assert "traceReadableMarkup(safeOutput,budget,8000)" in source


def test_trace_inspector_uses_raw_model_input_for_primary_prompt() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderModelChatPresentation(model)") : DASHBOARD_HTML.index(
            "function renderAgentLoopPresentation(model)"
        )
    ]
    assert "input=model.input??presentation.modelInput" in source
    assert "output=model.output??presentation.modelOutput" in source
    assert "traceModelChatEventTypes" in source
    assert "traceCodexTimeline({...model,events:timelineEvents,presentation:{...presentation,modelOutput:output,finalResponseStatus:finalStatus}}" in source


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


def test_trace_inspector_keeps_universal_summary_inside_optional_panels() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert "traceDisplayModel(d)" in source
    assert "universalSummary=traceSummary(model,unavailableCopy)" in source
    assert "${header}${primaryMarkup}${optionalMarkup}" in source
    assert "${universalSummary}<nav" in source
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


def test_trace_inspector_exposes_core_panels_when_human_presentation_is_empty() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    helper_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function tracePrimaryFallback(") : DASHBOARD_HTML.index(
            "function traceDisplayModel(detail)"
        )
    ]
    script = (
        helper_source
        + "const panels=[{id:'input',available:true,render:()=>'<section>input</section>'},{id:'output',available:true,render:()=>'<section>output</section>'},{id:'timeline',available:true,render:()=>'<section>timeline</section>'}];"
        + "console.log(tracePrimaryFallback('',panels));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = result.stdout
    assert "input" in rendered
    assert "output" in rendered
    assert "timeline" not in rendered

    detail_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert "function tracePrimaryFallback(" in DASHBOARD_HTML
    assert "primaryMarkup=tracePrimaryFallback(presentationMarkup,panels)" in detail_source
    assert "${header}${primaryMarkup}${optionalMarkup}" in detail_source


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
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    assert "structured" in result.stdout
    assert "[object Object]" not in result.stdout


def test_trace_inspector_dispatches_primary_body_before_optional_technical_details() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    assert "const presentationMarkup=renderTracePresentation(model),primaryMarkup=tracePrimaryFallback(presentationMarkup,panels);" in source
    assert "const optionalMarkup=`<details class=\"trace-optional-details\"" in source
    assert source.index("renderTracePresentation(model)") < source.index(
        "const optionalMarkup="
    )
    assert "${header}${primaryMarkup}${optionalMarkup}" in source
    assert "tracePrimaryFallback(presentationMarkup,panels)" in source


def test_trace_detail_runtime_keeps_primary_first_and_technical_details_closed() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    detail_start = DASHBOARD_HTML.index("function traceDisplayModel(detail){")
    source = _trace_presentation_runtime_source() + DASHBOARD_HTML[
        detail_start : DASHBOARD_HTML.index("function setTraceView(view)")
    ]
    fixture = {
        "terminal": True,
        "session": {
            "kind": "request",
            "action": "/api/command",
            "agent": "fixture-agent",
            "model": "fixture-model",
            "request": {"prompt": "run pytest"},
            "output": "fixture output",
        },
        "events": [
            {"seq": 1, "event_type": "output_stream", "payload": {"text": "fixture timeline output"}}
        ],
        "events_total": 1,
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false,traceOptionalDetailsOpen=false,traceView='timeline',activeTraceData=null,traceOpenSteps=new Set();"
        "const nodes={tracePageBody:null,tracePageTitle:{},tracePageLive:{}};"
        "const body={innerHTML:'',className:'',closest:()=>({scrollTop:0,scrollLeft:0}),querySelector(selector){return selector==='#traceTechnicalDetails'&&this.innerHTML?{open:technicalDetailsOpen}:null},querySelectorAll:()=>[]};"
        "let technicalDetailsOpen=false;nodes.tracePageBody=body;function $(id){return nodes[id]||null;}"
        "const window={requestAnimationFrame:fn=>fn()};const document={querySelectorAll:()=>[]};"
        + source
        + f"const fixture={json.dumps(fixture)};"
        + "renderTraceDetail(fixture);const first=body.innerHTML;"
        + "technicalDetailsOpen=true;renderTraceDetail(fixture);const restored=body.innerHTML;"
        + "traceView='raw';renderTraceDetail(fixture);const rawView=body.innerHTML;"
        + "console.log(JSON.stringify({first,restored,rawView}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    first = output["first"]
    restored = output["restored"]
    raw_view = output["rawView"]
    details_pattern = re.compile(r'<details\b(?=[^>]*\bid=[\"\']traceTechnicalDetails[\"\'])([^>]*)>')
    first_details = details_pattern.search(first)
    restored_details = details_pattern.search(restored)
    assert first_details and not re.search(r"\bopen(?:\s*=\s*(?:[\"'][^\"']*[\"']|[^\s>]+))?", first_details.group(1))
    assert restored_details and re.search(r"\bopen(?:\s*=\s*(?:[\"'][^\"']*[\"']|[^\s>]+))?", restored_details.group(1))
    assert first.index("trace-primary") < first.index('id="traceTechnicalDetails"')
    for marker in [
        "Universal request summary",
        'class="trace-tabs"',
        "Timeline",
        "data-trace-reveal",
        "Trace details are redacted by default.",
    ]:
        assert marker in first
    assert "Raw JSON" in raw_view


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
    assert "${header}${primaryMarkup}${optionalMarkup}" in detail_source
    assert "${universalSummary}<nav" in detail_source
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
    assert which("node"), "Dashboard JavaScript tests require Node.js"
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

    runtime_source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "kind": "model_chat",
            "modelInput": {"model": "fixture-model", "prompt": "human prompt"},
            "modelOutput": "human response",
            "thinking": "reasoning note",
            "chatTurns": [],
        }
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + runtime_source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = json.loads(result.stdout)
    for value in ["fixture-model", "human prompt", "human response", "reasoning note"]:
        assert value in rendered
    assert "[object Object]" not in rendered


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
        ],
        "renderRequestResponsePresentation(model)": [
            "request",
            "input",
            "response",
            "output",
            "status",
            "timing",
            "error",
            "tracePresentationColumns",
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


TRACE_PRESENTATION_CONTRACT_FIXTURES = {
    "model_chat": {
        "presentation": {
            "kind": "model_chat",
            "modelInput": {"prompt": "Explain trace retention", "headers": {"authorization": "MODEL_HEADER_MARKER"}},
            "modelOutput": None,
        },
        "session": {"final_response_status": "empty"},
    },
    "agent_loop": {
        "presentation": {"kind": "agent_loop"},
        "input": {"prompt": "Inspect the repository"},
        "events": [
            {"event_type": "model_request", "step": "STEP_MARKER", "seq": "SEQ_MARKER", "payload": {"step": "PAYLOAD_STEP_MARKER", "requestId": "AGENT_REQUEST_ID_MARKER", "messages": [{"role": "user", "content": {"prompt": "inspect", "options": {"headers": {"authorization": "AGENT_REQUEST_HEADER_MARKER"}, "apiToken": "AGENT_REQUEST_TOKEN_MARKER"}}}]}},
            {"event_type": "assistant_thinking", "step": "THINKING_STEP_MARKER", "seq": "THINKING_SEQ_MARKER", "payload": {"step": "THINKING_PAYLOAD_STEP_MARKER", "content": {"reason": "planning", "callId": "AGENT_THINKING_CALL_ID_MARKER", "sequenceId": "AGENT_THINKING_SEQUENCE_ID_MARKER", "options": {"headers": {"x-trace": "AGENT_THINKING_HEADER_MARKER"}, "token": "AGENT_THINKING_TOKEN_MARKER"}}}},
            {"event_type": "tool_call", "step": "TOOL_STEP_MARKER", "seq": "TOOL_SEQ_MARKER", "payload": {"name": "search", "callId": "AGENT_CALL_ID_MARKER", "arguments": {"query": "trace", "options": {"headers": {"authorization": "AGENT_HEADER_MARKER"}, "timeout": 5, "accessToken": "AGENT_ACCESS_TOKEN_MARKER"}, "correlationId": "AGENT_CORRELATION_ID_MARKER"}}},
            {"event_type": "tool_result", "step": "RESULT_STEP_MARKER", "seq": "RESULT_SEQ_MARKER", "payload": {"name": "search", "callId": "AGENT_RESULT_CALL_ID_MARKER", "status": "completed", "result": {"value": "one match", "request_id": "AGENT_RESULT_REQUEST_ID_MARKER", "headers": {"authorization": "AGENT_RESULT_HEADER_MARKER"}, "token": "AGENT_RESULT_TOKEN_MARKER"}}},
        ],
    },
    "command": {
        "presentation": {
            "kind": "command",
            "command": {
                "command": "pytest",
                "args": ["-q"],
                "stdout": "1 passed",
                "stderr": "",
                "exit_code": 0,
                "success": True,
                "input": {"api_key": "TRACE_SECRET_MARKER", "note": "safe input"},
            },
        }
    },
    "review": {
        "presentation": {
            "kind": "review",
            "review": {
                "request": "Review renderer contract",
                "findings": [{"severity": "high", "message": "Add coverage"}],
                "recommendation": "Proceed after coverage",
                "status": "changes requested",
            },
        }
    },
    "repo_intelligence": {
        "presentation": {
            "kind": "repo_intelligence",
            "repoOperation": {
                "repository": "local-ai-hub",
                "operation": "search symbols",
                "query": "tracePresentationShell",
                "result": "one match",
            },
        }
    },
    "rag_search": {
        "presentation": {
            "kind": "rag_search",
            "retrieval": {
                "query": "renderer contract",
                "sources": [{"path": "dashboard.py", "provider": "index", "score": 0.9, "snippet": "safe shell"}],
                "answer": "Use bounded presentation helpers.",
            },
        }
    },
    "async_job": {
        "presentation": {
            "kind": "async_job",
            "asyncJob": {"status": "failed", "error": "worker timeout", "result": ""},
        },
        "correlations": {"async_job_id": "ASYNC_JOB_ID_MARKER", "request_id": "CORRELATION_ID_MARKER"},
        "lifecycle": {"state": "failed"},
    },
    "request_response": {
        "presentation": {"kind": "request_response"},
        "session": {"request": {"method": "POST", "path": "/trace", "headers": {"authorization": "REQUEST_HEADER_MARKER"}, "request_id": "REQUEST_ID_MARKER"}},
        "response": {"message": "accepted"},
        "output": "request completed",
        "lifecycle": {"state": "complete"},
        "timing": {"duration_ms": 18},
    },
}


def test_trace_inspector_shared_presentation_contract_covers_all_kinds() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "const n=v=>String(v??0);function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const fixtures={json.dumps(TRACE_PRESENTATION_CONTRACT_FIXTURES)};"
        + "const renderers={model_chat:renderModelChatPresentation,agent_loop:renderAgentLoopPresentation,command:renderCommandPresentation,review:renderReviewPresentation,repo_intelligence:renderRepoIntelligencePresentation,rag_search:renderRagSearchPresentation,async_job:renderAsyncJobPresentation,request_response:renderRequestResponsePresentation};"
        + "const rendered=Object.fromEntries(Object.entries(fixtures).map(([kind,model])=>[kind,renderers[kind](model)]));"
        + "console.log(JSON.stringify(rendered));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = json.loads(result.stdout)
    expected_values = {
        "model_chat": ["Explain trace retention", "Model returned an empty final response"],
        "agent_loop": ["search", "completed", "one match"],
        "command": ["pytest", "1 passed"],
        "review": ["Review renderer contract", "Add coverage"],
        "repo_intelligence": ["local-ai-hub", "tracePresentationShell"],
        "rag_search": ["renderer contract", "safe shell"],
        "async_job": ["failed", "worker timeout"],
        "request_response": ["/trace", "request completed"],
    }
    for kind, values in expected_values.items():
        html = rendered[kind]
        primary = html.split('<details class="trace-secondary-details', 1)[0]
        assert re.search(r'class="[^"]*\btrace-primary-section\b[^"]*"', html)
        assert '<details class="trace-secondary-details' in html
        assert 'data-trace-primary-group="Technical details"' in html
        assert not re.search(r'<details class="trace-secondary-details[^>]*\bopen(?:=|\s|>)', html)
        assert len(re.findall(r'<section[^>]*class="[^"]*\btrace-primary-section\b[^"]*"', html)) == 1
        for value in values:
            assert value in primary, f"{kind} renderer omitted visible primary value {value!r}"
        assert "[object Object]" not in html
        for marker in [
            "TRACE_SECRET_MARKER",
            "MODEL_HEADER_MARKER",
            "ASYNC_JOB_ID_MARKER",
            "CORRELATION_ID_MARKER",
            "REQUEST_HEADER_MARKER",
            "REQUEST_ID_MARKER",
        ]:
            assert marker not in primary
        if kind == "agent_loop":
            for marker in [
                "STEP_MARKER", "SEQ_MARKER", "PAYLOAD_STEP_MARKER", "THINKING_STEP_MARKER", "THINKING_SEQ_MARKER",
                "THINKING_PAYLOAD_STEP_MARKER", "TOOL_STEP_MARKER", "TOOL_SEQ_MARKER", "RESULT_STEP_MARKER", "RESULT_SEQ_MARKER",
                "AGENT_CALL_ID_MARKER", "AGENT_RESULT_CALL_ID_MARKER", "AGENT_THINKING_CALL_ID_MARKER",
                "AGENT_REQUEST_ID_MARKER", "AGENT_CORRELATION_ID_MARKER", "AGENT_THINKING_SEQUENCE_ID_MARKER",
                "AGENT_HEADER_MARKER", "AGENT_REQUEST_HEADER_MARKER", "AGENT_THINKING_HEADER_MARKER", "AGENT_RESULT_HEADER_MARKER",
                "AGENT_ACCESS_TOKEN_MARKER", "AGENT_REQUEST_TOKEN_MARKER", "AGENT_THINKING_TOKEN_MARKER", "AGENT_RESULT_TOKEN_MARKER",
            ]:
                assert marker not in primary
        if kind == "model_chat":
            assert "Model returned an empty final response" in primary
            assert "Final response not captured" not in primary


def test_trace_inspector_shell_sanitizes_prebuilt_attention_markup() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + "console.log(tracePresentationShell('title','subtitle','<p>primary</p>','<p>secondary</p>','<section class=\"trace-attention-section\"><img src=x onerror=bad></section>'));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    assert "<img" not in result.stdout
    assert "&lt;section class=&quot;trace-attention-section&quot;&gt;" in result.stdout


def test_trace_inspector_restores_all_collapsible_presentation_details() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    assert "function captureTraceCollapsibleDetails(" in DASHBOARD_HTML
    assert "function restoreTraceCollapsibleDetails(" in DASHBOARD_HTML
    assert 'data-trace-key="model-timeline"' in DASHBOARD_HTML
    assert 'data-trace-key="model-context"' in DASHBOARD_HTML
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceCollapsibleKey(") : DASHBOARD_HTML.index(
            "function traceEventList("
        )
    ]
    script = (
        source
        + "const nodes=[{dataset:{traceKey:'model-timeline'},open:true},{dataset:{traceKey:'model-context'},open:false}];"
        + "const root={querySelectorAll:()=>nodes};const state=captureTraceCollapsibleDetails(root);nodes.forEach(node=>node.open=false);restoreTraceCollapsibleDetails(root,state);console.log(JSON.stringify(nodes.map(node=>node.open)));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [True, False]


def test_trace_renderers_render_per_kind_fixtures_as_semantic_output() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixtures = {
        "command": {
            "presentation": {
                "kind": "command",
                "command": {
                    "command": "pytest",
                    "args": ["-q", "--json"],
                    "stdout": "build complete",
                    "stderr": "minor warning",
                    "exit_code": 0,
                    "retries": 2,
                    "duration_ms": 125,
                },
            }
        },
        "review": {
            "presentation": {
                "kind": "review",
                "review": {
                    "request": "Review this patch",
                    "context": "dashboard contract",
                    "diff": "- old\n+ new",
                    "findings": [{"severity": "critical", "message": "Null check"}],
                    "recommendation": "merge after fix",
                    "status": "changes requested",
                },
            }
        },
        "repo_intelligence": {
            "presentation": {
                "kind": "repo_intelligence",
                "repoOperation": {
                    "repository": "local-ai-hub",
                    "operation": "search symbols",
                    "query": "tracePresentation",
                    "files": ["dashboard.py", "custom_modals.py"],
                    "symbols": ["traceRenderBudget", "traceList"],
                    "result": "3 matches",
                },
            }
        },
        "rag_search": {
            "presentation": {
                "kind": "rag_search",
                "retrieval": {
                    "query": "trace contract",
                    "sources": [
                        {
                            "path": "dashboard.py",
                            "start_line": 2200,
                            "provider": "serena",
                            "score": 0.91,
                            "snippet": "semantic renderer",
                        },
                        {
                            "path": "plan.md",
                            "start_line": 17,
                            "provider": "index",
                            "score": 0.72,
                            "snippet": "bounded output",
                        },
                    ],
                    "answer": "Use the semantic contract",
                    "truncated": True,
                },
            }
        },
        "async_job": {
            "presentation": {
                "kind": "async_job",
                "asyncJob": {
                    "status": "queued",
                    "queue_wait_ms": 125,
                    "retries": 2,
                    "result": "job result",
                    "error": "timeout recovered",
                },
            },
            "lifecycle": {"state": "running"},
        },
        "request_response": {
            "presentation": {"kind": "request_response"},
            "session": {"request": {"method": "POST", "path": "/chat"}},
            "response": {"message": "ok"},
            "output": "response text",
            "lifecycle": {"state": "complete"},
            "timing": {"duration_ms": 42},
            "errors": ["transport failed"],
        },
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + f"const fixtures={json.dumps(fixtures)};"
        + "const rendered=Object.fromEntries(Object.entries(fixtures).map(([kind,model])=>[kind,renderTracePresentation(model)]));"
        + "console.log(JSON.stringify(rendered));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = json.loads(result.stdout)
    expected = {
        "command": ["Command and arguments", "--json", "stdout", "build complete", "stderr", "exit code", "retries", "duration"],
        "review": ["Review this patch", "dashboard contract", "diff", "findings", "critical", "Null check", "merge after fix", "changes requested"],
        "repo_intelligence": ["local-ai-hub", "search symbols", "tracePresentation", "dashboard.py", "custom_modals.py", "traceRenderBudget", "3 matches"],
        "rag_search": ["trace contract", "2 results", "dashboard.py", "line 2200", "serena", "0.91", "semantic renderer", "Use the semantic contract", "Truncation"],
        "async_job": ["running", "queued", "queue wait", "125", "retries", "job result", "timeout recovered"],
        "request_response": ["POST", "/chat", "ok", "response text", "complete", "timing", "42", "transport failed"],
    }
    for kind, labels in expected.items():
        html = rendered[kind]
        for label in labels:
            assert label in html, f"{kind} renderer omitted {label!r}"
        assert "[object Object]" not in html
        assert not re.search(r"\{\s*[\"'][A-Za-z_][\w-]*[\"']\s*:", html)
    assert "trace-code-card" in rendered["command"]
    assert "trace-list-card" in rendered["command"]
    assert "trace-code-card" in rendered["review"]
    assert "trace-list-card" in rendered["review"]
    assert "trace-list-card" in rendered["repo_intelligence"]
    assert "trace-search-result-row" in rendered["rag_search"]
    assert "trace-code-card" in rendered["async_job"]
    assert "trace-code-card" in rendered["request_response"]


def test_trace_async_and_request_response_outputs_keep_full_human_code_blocks() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + "const asyncOutput='async-output-'+ 'x'.repeat(16000);"
        + "const responseOutput='response-output-'+ 'y'.repeat(16000);"
        + "const asyncHtml=renderAsyncJobPresentation({presentation:{kind:'async_job',asyncJob:{result:asyncOutput}},lifecycle:{}});"
        + "const responseHtml=renderRequestResponsePresentation({presentation:{kind:'request_response'},output:responseOutput});"
        + "console.log(JSON.stringify({asyncHtml,responseHtml,asyncOutput,responseOutput}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    for html, payload, marker in (
        (output["asyncHtml"], output["asyncOutput"], "async-output-"),
        (output["responseHtml"], output["responseOutput"], "response-output-"),
    ):
        assert "trace-code-card" in html
        assert marker in html
        assert len(html) > 12000
        assert payload.endswith("x" * 100 if marker == "async-output-" else "y" * 100)
        assert "[object Object]" not in html
        assert not re.search(r"\{\s*[\"'][A-Za-z_][\w-]*[\"']\s*:", html)


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
    assert "stdout" in rendered["command"]
    assert "none" not in rendered["command"]
    assert "rank" in rendered["rag"].lower() and "score" in rendered["rag"].lower()
    assert rendered["rag"].count("trace-search-result-row") == 2
    assert '<details class="trace-secondary-details' in rendered["rag"]
    assert not re.search(r'<details class="trace-secondary-details[^>]*\bopen(?:=|\s|>)', rendered["rag"])
    assert "answer" in rendered["rag"]


def test_trace_presentation_starts_specialized_review_without_generic_input_output() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "kind": "review",
            "review": {"request": "review request", "findings": []},
        },
        "input": "model prompt",
        "output": "model answer",
        "lifecycle": {"state": "done"},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const model={json.dumps(fixture)};"
        + "console.log(renderTracePresentation(model));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = result.stdout
    assert "<h2>Input / output</h2>" not in rendered
    assert ">Review</h2>" in rendered


def test_trace_presentation_does_not_prepend_generic_json_like_input_output_to_specialized_requests() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "kind": "command",
            "command": {
                "command": "pytest",
                "args": ["-q"],
                "input": {"action": "run", "cwd": "C:/workspace"},
                "stdout": "2 passed",
                "exit_code": 0,
            },
        },
        "input": {"action": "run", "cwd": "C:/workspace", "command": "pytest"},
        "output": {"success": True, "stdout": "2 passed", "exit_code": 0},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(renderTracePresentation({json.dumps(fixture)}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = result.stdout
    assert "<h3>Command and arguments</h3>" in rendered
    assert "<h2>Input / output</h2>" not in rendered
    assert rendered.index("Command and arguments") < rendered.index("Command output")
    assert "pytest" in rendered
    assert "2 passed" in rendered
    assert "Auto Fix" not in rendered


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


def test_trace_unknown_malformed_and_missing_content_use_safe_bounded_fallbacks() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    oversized = "bounded-output-" + ("x" * 16000)
    fixtures = {
        "unknown": {
            "presentation": {"kind": "unknown"},
            "input": {"message": "fallback input", "internal_id": "hidden-id"},
            "output": {"answer": "fallback output"},
        },
        "malformed": {
            "presentation": {"kind": "unknown"},
            "input": {"payload": "malformed input", "nested": {"value": "kept"}},
            "output": {"result": "malformed output"},
            "events": [{"event_type": "event", "payload": "broken payload"}],
        },
        "missing": {
            "presentation": {"kind": "model_chat", "modelInput": None, "modelOutput": None},
            "events": [],
        },
        "bounded": {
            "presentation": {"kind": "unknown"},
            "input": {"api_key": "fallback-secret", "text": oversized},
        },
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + f"const fixtures={json.dumps(fixtures)};"
        + "const rendered={unknown:renderTracePresentation(fixtures.unknown),malformed:renderTracePresentation(fixtures.malformed),missing:renderModelChatPresentation(fixtures.missing),bounded:renderTracePresentation(fixtures.bounded)};"
        + "console.log(JSON.stringify(rendered));"
    )
    rendered = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "Input / output" in rendered["unknown"]
    assert "fallback input" in rendered["unknown"] and "fallback output" in rendered["unknown"]
    assert "hidden-id" not in rendered["unknown"]
    assert "malformed input" in rendered["malformed"] and "kept" in rendered["malformed"]
    assert "malformed output" in rendered["malformed"]
    assert "No prompt captured" in rendered["missing"]
    assert "No response captured" not in rendered["missing"]
    for html in rendered.values():
        assert "[object Object]" not in html
        assert not re.search(r"\{\s*[\"'][A-Za-z_$][\w$]*\s*:", html)
    assert "fallback-secret" not in rendered["bounded"]
    assert len(rendered["bounded"]) > 12000
    assert oversized[-100:] in rendered["bounded"]


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
    start = re.search(r"(?m)^[^\r\n]*\r?\n(?=\s*function\s+renderAny\s*\()", DASHBOARD_HTML)
    assert start, "Trace presentation runtime start missing"
    end = re.search(r"\bfunction\s+traceDisplayModel\s*\([^)]*\)\s*\{", DASHBOARD_HTML[start.end() :])
    assert end, "Trace presentation runtime end missing"
    return DASHBOARD_HTML[start.start() : start.end() + end.start()]


def test_trace_search_runtime_is_compact_and_keeps_one_result_per_row() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {"kind": "rag_search", "retrieval": {}},
        "input": {"query": "renderTracePresentation", "root": "C:/workspace/hub", "top_k": 12, "enrich": False},
        "output": {
            "success": True,
            "results": [
                {"path": "docs/trace.md", "start_line": 2, "end_line": 12, "score": 11.5, "text": "Trace presentation guide", "file_sha256": "secret-sha", "evidence_id": "secret-evidence"},
                {"path": "src/dashboard.js", "start_line": 8, "end_line": 10, "score": 8.2, "text": "Human trace UI"},
            ],
        },
        "identity": {"action": "/api/search"},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderTracePresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "renderTracePresentation" in html
    assert "<h2>Input / output</h2>" not in html
    assert html.count("trace-search-result-row") == 2
    assert "docs/trace.md" in html and "Trace presentation guide" in html
    assert "file_sha256" not in html and "evidence_id" not in html


def test_trace_model_runtime_labels_prompt_and_response_as_primary_content() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {"kind": "model_chat", "modelInput": {"prompt": "Explain traces"}, "modelOutput": "They show inputs and outputs."},
        "events": [], "session": {}, "actor": {}, "correlations": {}, "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "Prompt" in html and "Response" in html
    assert "Explain traces" in html and "They show inputs and outputs." in html


def test_trace_model_runtime_exposes_capture_state_and_detail_controls() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {"kind": "model_chat", "modelInput": {"prompt": "Explain traces"}},
        "events": [],
        "session": {"final_response_status": "empty"},
        "actor": {}, "correlations": {}, "identity": {},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + f"const m={{...{json.dumps(fixture)},captureStates:{{output:'empty'}}}};"
        + "console.log(JSON.stringify({html:renderModelChatPresentation(m),state:traceCaptureState('', 'empty')}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = json.loads(result.stdout)
    assert rendered["state"] == "empty"
    assert "Final response" in rendered["html"]
    assert "Empty" in rendered["html"]
    assert "data-trace-expand-all" in rendered["html"]
    assert "data-trace-collapse-all" in rendered["html"]
    assert "data-trace-copy-final" in rendered["html"]


def test_trace_model_chat_runtime_surfaces_primary_summary_and_closed_focus_sections() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "kind": "model_chat",
            "modelInput": {
                "model": "fixture-model",
                "messages": [{"role": "user", "content": "Explain traces"}],
                "options": {"temperature": 0.2},
                "request": {"path": "/model"},
            },
            "modelOutput": "They show inputs and outputs.",
            "thinking": "Reasoning stays secondary.",
        },
        "toolCalls": [
            {
                "call": {"name": "search", "arguments": {"query": "traces"}},
                "result": {"status": "completed", "result": {"value": "one match"}},
            }
        ],
        "session": {"model": "fixture-model", "final_response_status": "complete"},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderModelChatPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    primary = html.split('<details class="trace-secondary-details', 1)[0]
    assert "Explain traces" in primary
    assert "They show inputs and outputs." in primary
    assert "Final response" in primary and "Produced" in primary
    assert "Tool summary" in primary and "search" in primary and "completed" in primary
    assert "Request envelope" in html
    assert '<details class="trace-optional-details trace-thinking-panel"' in html
    assert '<details class="trace-optional-details trace-model-context"' in html
    assert '<details class="trace-optional-details trace-model-timeline"' in html
    for marker in ["Thinking / reasoning", "Model context", "Request envelope", "Execution timeline"]:
        assert f"<summary>{marker}" in html


def test_trace_agent_loop_runtime_surfaces_primary_state_ordered_tools_and_closed_raw_details() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "kind": "agent_loop",
            "objective": "Inspect the repository",
            "modelInput": {"prompt": "Inspect the repository"},
            "modelOutput": {"summary": "one match"},
        },
        "input": {"prompt": "Inspect the repository"},
        "output": {"summary": "one match"},
        "errors": {"message": "worker timeout"},
        "lifecycle": {"state": "failed", "phase": "tool execution"},
        "correlations": {"request_id": "hidden-correlation"},
        "events": [
            {"event_type": "tool_call", "payload": {"name": "search", "call_id": "c1", "arguments": {"query": "trace"}}},
            {"event_type": "tool_result", "payload": {"name": "search", "call_id": "c1", "status": "completed", "result": {"value": "one match"}}},
        ],
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderAgentLoopPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    primary = html.split('<details class="trace-secondary-details', 1)[0]
    assert "Objective" in primary and "Inspect the repository" in primary
    assert "Lifecycle" in primary and "failed" in primary
    assert "Final result" in primary and "one match" in primary
    assert "Failure summary" in primary and "worker timeout" in primary
    assert "Tool summary" in primary and "search" in primary and "completed" in primary
    assert "hidden-correlation" not in primary
    for marker in ["Raw tool payloads", "Full event metadata", "Correlations", "Execution timeline"]:
        assert f"<summary>{marker}" in html


def test_trace_agent_loop_runtime_exposes_missing_states_and_one_empty_state() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    redact = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    fixture = {"presentation": {"kind": "agent_loop"}, "correlations": {}}
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        + redact
        + "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderAgentLoopPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    primary = html.split('<details class="trace-secondary-details', 1)[0]
    assert "Objective not captured" in primary
    assert "Input not captured" in primary
    assert "Final result not captured" in primary
    assert "No agent trace events captured" in primary
    assert "Raw tool payloads" not in html
    assert "Full event metadata" not in html
    assert "Correlations" not in html
    assert "Execution timeline" not in html
    assert html.count('class="trace-secondary-details') == 1


def test_trace_agent_loop_runtime_prioritizes_failure_and_preserves_safe_correlations() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    redact = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    fixtures = {
        "failure_without_lifecycle": {
            "presentation": {"kind": "agent_loop"},
            "errors": {"message": "failed worker"},
        },
        "success_false_without_lifecycle": {
            "presentation": {"kind": "agent_loop"},
            "success": False,
            "events": [{"event_type": "tool_call", "payload": {"name": "search"}}],
        },
        "interrupted": {"presentation": {"kind": "agent_loop"}, "lifecycle": {"state": "interrupted"}},
        "queued": {"presentation": {"kind": "agent_loop"}, "lifecycle": {"state": "queued"}},
        "running": {"presentation": {"kind": "agent_loop"}, "lifecycle": {"state": "running"}},
        "live": {
            "presentation": {"kind": "agent_loop"},
            "events": [{"event_type": "model_request", "payload": {"prompt": "work"}}],
        },
        "correlations": {
            "presentation": {"kind": "agent_loop"},
            "correlations": {
                "scope": "workspace",
                "relationship": "parent-child",
                "request_id": "INTERNAL_ID",
                "headers": {"authorization": "CORRELATION_SECRET"},
                "apiToken": "CORRELATION_TOKEN",
            },
        },
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        + redact
        + "let traceRevealRedactedDetails=false;"
        + source
        + f"const fixtures={json.dumps(fixtures)};const output=Object.fromEntries(Object.entries(fixtures).map(([k,v])=>[k,renderAgentLoopPresentation(v)]));console.log(JSON.stringify(output));"
    )
    rendered = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    for key in ["failure_without_lifecycle", "success_false_without_lifecycle"]:
        assert "failed" in rendered[key].split('<details class="trace-secondary-details', 1)[0]
    assert "interrupted" in rendered["interrupted"]
    assert "queued" in rendered["queued"]
    assert "running" in rendered["running"]
    assert "live" in rendered["live"]
    correlation_html = rendered["correlations"]
    assert "Correlations" in correlation_html
    assert "workspace" in correlation_html and "parent-child" in correlation_html
    for marker in ["INTERNAL_ID", "CORRELATION_SECRET", "CORRELATION_TOKEN", "request_id", "authorization", "apiToken"]:
        assert marker not in correlation_html


def test_trace_agent_loop_runtime_bounds_malformed_redacted_and_truncated_values() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    redact = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function redactDiagnostic(") : DASHBOARD_HTML.index(
            "// Lightweight pure-canvas"
        )
    ]
    oversized = "payload-" + ("z" * 50000)
    fixture = {
        "presentation": {
            "kind": "agent_loop",
            "objective": oversized,
            "modelInput": {"messages": [{"role": "user", "content": oversized}]},
            "modelOutput": {"apiToken": "REDACTED_TOKEN", "value": oversized},
        },
        "events": [
            {"event_type": "broken", "payload": "MALFORMED_PAYLOAD"},
            {"event_type": "tool_result", "payload": {"error": {"apiToken": "REDACTED_SECRET"}, "result": {"value": oversized}}},
        ],
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        + redact
        + "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderAgentLoopPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "Malformed event payload" in html
    assert "REDACTED_TOKEN" not in html and "REDACTED_SECRET" not in html
    assert "payload budget" in html.lower()
    assert len(html) < 80000


def test_trace_detail_controls_are_present_and_technical_details_start_closed() -> None:
    detail_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    handler_source = DASHBOARD_HTML
    assert "presentationMarkup" in detail_source
    assert "traceTechnicalDetails" in detail_source
    assert "setTraceDetailsOpen(true)" in handler_source
    assert "setTraceDetailsOpen(false)" in handler_source


def test_trace_history_surfaces_project_before_technical_metadata() -> None:
    assert "function traceProjectLabel(" in DASHBOARD_HTML
    assert "<th>Project</th>" in DASHBOARD_HTML
    source = DASHBOARD_HTML[DASHBOARD_HTML.index("function renderTraceList(items)") : DASHBOARD_HTML.index("async function pollTraces")]
    assert "traceProjectLabel" in source
    request_source = DASHBOARD_HTML[DASHBOARD_HTML.index("function workRecentRequestRow(request)") : DASHBOARD_HTML.index("function renderAdoptionRows")]
    assert "traceProjectLabel" in request_source


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
    assert "bad-1" not in html and "ok-1" not in html


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
    assert "run" in html and "failed" in html and "c1" not in html


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


def test_trace_legacy_timeline_renders_structured_output_without_object_coercion() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + "const event={event_type:'output_stream',payload:{text:{answer:'structured'}}};"
        + "console.log(JSON.stringify({body:traceEventBody(event,[],0),compact:compactTimelineEvents([{event_type:'output_delta',payload:{text:{answer:'structured'}}}])}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    assert "[object Object]" not in output["body"]
    assert "Answer" in output["body"]
    assert "[object Object]" not in json.dumps(output["compact"])


def test_trace_legacy_output_stream_keeps_full_human_payload() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + "const streamPayload='legacy-stream-'+ 'x'.repeat(16000);"
        + "const deltaPayload='legacy-delta-'+ 'y'.repeat(16000);"
        + "const streamBody=traceEventBody({event_type:'output_stream',payload:{text:streamPayload}},[],0);"
        + "const deltaBody=traceEventBody({event_type:'output_delta',payload:{text:deltaPayload}},[],0);"
        + "console.log(JSON.stringify({streamBody,deltaBody,streamPayload,deltaPayload}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    for body, payload, marker in (
        (output["streamBody"], output["streamPayload"], "legacy-stream-"),
        (output["deltaBody"], output["deltaPayload"], "legacy-delta-"),
    ):
        assert marker in body
        assert len(body) > 10000
        assert payload.endswith("x" * 100 if marker == "legacy-stream-" else "y" * 100)


def test_trace_text_fallback_and_event_labels_stay_human_readable() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));const n=v=>String(v??0);"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + "console.log(JSON.stringify({prompt:promptText({answer:'structured',nested:{count:1}}),summary:traceEventSummary('model_request',{model:{name:'fixture'}})}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    assert "[object Object]" not in output["prompt"]
    assert "Answer: structured" in output["prompt"]
    assert "Nested" in output["prompt"]
    assert "[object Object]" not in output["summary"]
    assert output["summary"] == "Request to fixture"


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


def test_trace_primary_fields_hide_empty_internal_and_duplicate_values() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "command": {
            "command": "pytest",
            "args": ["-q"],
            "input": {
                "message": "meaningful input",
                "status": "empty",
                "empty_value": "",
                "null_value": None,
                "internal_id": "internal-id-123",
                "request_id": "request-id-123",
                "trace_id": "trace-id-123",
                "metadata": {
                    "source": "duplicate-metadata",
                    "action": "duplicate-metadata",
                },
            },
            "stdout": "useful stdout",
            "stderr": "none",
            "exit_code": 0,
            "retries": "",
            "duration_ms": None,
        }
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const m={{presentation:{json.dumps(fixture)},lifecycle:{{}},correlations:{{}},session:{{}},identity:{{}}}};"
        + "console.log(JSON.stringify(renderCommandPresentation(m)));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    html = json.loads(result.stdout)
    assert "pytest" in html
    assert "meaningful input" in html
    assert "useful stdout" in html
    for hidden in [
        "empty_value",
        "null_value",
        "internal-id-123",
        "request-id-123",
        "trace-id-123",
        "duplicate-metadata",
        "No stderr captured",
        "No retries captured",
        "No duration captured",
    ]:
        assert hidden not in html


def test_trace_primary_presentations_use_semantic_value_renderers() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    renderer_names = [
        "renderCommandPresentation",
        "renderReviewPresentation",
        "renderRepoIntelligencePresentation",
        "renderRagSearchPresentation",
        "renderAsyncJobPresentation",
        "renderRequestResponsePresentation",
    ]

    fixtures = {
        "command": {
            "presentation": {"kind": "command", "command": {"command": "pytest", "args": ["-q"], "input": {"stdin": "input text", "options": {"timeout": 5}}, "stdout": "command output", "exit_code": 0, "retries": 1, "duration_ms": 12}},
            "lifecycle": {}, "correlations": {}, "session": {}, "identity": {},
        },
        "review": {
            "presentation": {"kind": "review", "review": {"request": {"target": "dashboard.py"}, "context": {"files": ["dashboard.py", "tests.py"]}, "diff": "+ semantic renderer", "findings": [{"severity": "high", "message": "use semantic card"}], "recommendation": "refactor", "status": "open"}},
            "lifecycle": {}, "correlations": {}, "session": {}, "identity": {},
        },
        "repo": {
            "presentation": {"kind": "repo_intelligence", "repoOperation": {"repository": "local-ai-hub", "root": "C:/workspace", "operation": "search", "query": "trace", "files": ["dashboard.py"], "symbols": {"count": 2}, "context": {"summary": "repository context"}, "result": {"matches": 1}}},
            "lifecycle": {}, "correlations": {}, "session": {}, "identity": {},
        },
        "rag": {
            "presentation": {"kind": "rag_search", "retrieval": {"query": "trace presentation", "sources": [{"score": 0.9, "provider": "index", "content": "semantic result"}], "answer": "use cards", "truncated": False}},
            "lifecycle": {}, "correlations": {}, "session": {}, "identity": {},
        },
        "asyncJob": {
            "presentation": {"kind": "async_job", "asyncJob": {"status": "running", "queue_wait_ms": 4, "retries": 1, "worker_input": {"job": "trace"}, "result": ["partial result"]}},
            "lifecycle": {}, "correlations": {}, "session": {}, "identity": {},
        },
        "request": {
            "presentation": {"kind": "request_response"}, "input": "request body", "output": ["response body"], "timing": {"duration_ms": 20}, "response": {"status": 200},
            "lifecycle": {"status_code": 200}, "correlations": {}, "session": {"request": {"path": "/trace"}}, "identity": {},
        },
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const fixtures={json.dumps(fixtures)};"
        + "console.log(JSON.stringify({command:renderCommandPresentation(fixtures.command),review:renderReviewPresentation(fixtures.review),repo:renderRepoIntelligencePresentation(fixtures.repo),rag:renderRagSearchPresentation(fixtures.rag),asyncJob:renderAsyncJobPresentation(fixtures.asyncJob),request:renderRequestResponsePresentation(fixtures.request)}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = json.loads(result.stdout)
    semantic_markers = ["trace-summary-card", "trace-code-card", "trace-list-card", "trace-timeline"]
    output_keys = {
        "renderCommandPresentation": "command",
        "renderReviewPresentation": "review",
        "renderRepoIntelligencePresentation": "repo",
        "renderRagSearchPresentation": "rag",
        "renderAsyncJobPresentation": "asyncJob",
        "renderRequestResponsePresentation": "request",
    }
    expected_pairs = {
        "command": ["Command and arguments", "pytest", "-q", "input text", "command output", "exit code", "0"],
        "review": ["Review", "dashboard.py", "+ semantic renderer", "use semantic card", "refactor", "open"],
        "repo": ["Repository intelligence", "local-ai-hub", "trace", "dashboard.py", "repository context", "1"],
        "rag": ["Search", "Query", "trace presentation", "semantic result", "0.9", "use cards"],
        "asyncJob": ["Async job", "running", "queue wait", "trace", "partial result", "1"],
        "request": ["Request / response", "/trace", "request body", "response body", "200"],
    }
    for function_name in renderer_names:
        output_key = output_keys[function_name]
        output = rendered[output_key]
        for pair in expected_pairs[output_key]:
            assert pair in output, f"{output_key}: missing {pair}"
        assert any(marker in output for marker in semantic_markers), function_name
        assert "[object Object]" not in output
        assert not re.search(r"\{\s*[\"'][A-Za-z_$][\w$]*[\"']\s*:", output)


def test_trace_primary_columns_are_compact_collapsible_groups() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');} let traceRevealRedactedDetails=false;"
        + source
        + "const html=tracePresentationColumns('Demo',[traceSummaryCard('request','body',traceRenderBudget())],[],traceRenderBudget());"
        + "const missing=tracePresentationColumns('Empty',[],[],traceRenderBudget());"
        + "console.log(JSON.stringify({html,missing}));"
    )
    result = subprocess.run(["node"], input=script, check=True, capture_output=True, text=True)
    rendered = json.loads(result.stdout)
    html = rendered["html"]
    assert html.count('class="trace-primary-group"') == 1
    assert 'class="trace-primary-group" data-group="request" data-trace-primary-group="request" data-trace-collapsible open' in html
    assert '<summary><span>Request details</span>' in html
    assert 'open' in html
    assert 'No request details captured' not in html
    assert '<article' not in html
    assert 'No result details captured' not in rendered["missing"]


def test_trace_technical_details_are_closed_by_default() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderTraceDetail(d)") : DASHBOARD_HTML.index(
            "function setTraceView(view)"
        )
    ]
    details_tag = re.search(r"<details\b[^>]*>", source)
    assert details_tag, "Technical details disclosure markup missing"
    tag = details_tag.group(0)
    assert re.search(r"\bid\s*=\s*['\"]traceTechnicalDetails['\"]", tag)
    assert re.search(r"\bclass\s*=\s*['\"][^'\"]*\btrace-optional-details\b", tag)
    default_tag = re.sub(r"\$\{[^}]*\}", "", tag)
    assert not re.search(
        r"(?:^|\s)open(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?(?=\s|>)",
        default_tag,
    )
    assert re.search(r"\btraceOptionalDetailsOpen\s*=\s*false\b", DASHBOARD_HTML)


def test_trace_presentation_field_supports_explicit_technical_mode() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + "const html=tracePresentationField('arguments',{flag:'--json',nested:{count:2}},'No args captured',traceRenderBudget(),{mode:'technical'});"
        + "const stderr=tracePresentationField('stderr','none','No stderr captured',traceRenderBudget(),{mode:'technical'});"
        + "console.log(JSON.stringify({html,stderr}));"
    )
    rendered = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    html = rendered["html"]
    assert "human-grid" in html
    assert "Flag" in html and "--json" in html and "Count" in html and "2" in html
    assert "none" in rendered["stderr"]


def test_trace_structured_command_and_review_values_use_semantic_markup() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixtures = {
        "command": {
            "presentation": {"kind": "command", "command": {"command": "pytest", "args": [{"flag": "--format", "value": "json"}]}}
        },
        "review": {
            "presentation": {
                "kind": "review",
                "review": {"findings": [{"severity": "high", "rule": "R1", "details": {"message": "avoid generic object coercion"}}]},
            }
        },
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const fixtures={json.dumps(fixtures)};"
        + "console.log(JSON.stringify({command:renderCommandPresentation(fixtures.command),review:renderReviewPresentation(fixtures.review)}));"
    )
    rendered = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "--format" in rendered["command"] and "json" in rendered["command"]
    assert "R1" in rendered["review"] and "avoid generic object coercion" in rendered["review"]
    for html in rendered.values():
        assert "[object Object]" not in html
        assert not re.search(r"\{\s*[\"'][A-Za-z_$][\w$]*[\"']\s*:", html)


def test_trace_code_block_omits_none_like_values() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + "const values=['none','null','empty','n/a','unknown'].map(value=>traceCodeBlock('output',value,traceRenderBudget()));"
        + "console.log(JSON.stringify({values,meaningful:traceCodeBlock('output','real output',traceRenderBudget())}));"
    )
    rendered = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert rendered["values"] == ["", "", "", "", ""]
    assert "real output" in rendered["meaningful"]


def test_trace_primary_keeps_duplicate_word_in_meaningful_text() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixtures = {
        "command": {"presentation": {"kind": "command", "command": {"stdout": "duplicate output remains"}}},
        "review": {"presentation": {"kind": "review", "review": {"findings": "duplicate finding text remains"}}},
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"const fixtures={json.dumps(fixtures)};"
        + "console.log(JSON.stringify({command:renderCommandPresentation(fixtures.command),review:renderReviewPresentation(fixtures.review)}));"
    )
    rendered = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "duplicate output remains" in rendered["command"]
    assert "duplicate finding text remains" in rendered["review"]


def test_trace_review_object_severity_uses_human_text() -> None:
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    source = _trace_presentation_runtime_source()
    fixture = {
        "presentation": {
            "kind": "review",
            "review": {"findings": [{"severity": {"level": "high"}, "message": "object severity"}]},
        }
    }
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "function redactDiagnostic(value){return String(value??'');}"
        "let traceRevealRedactedDetails=false;"
        + source
        + f"console.log(JSON.stringify(renderReviewPresentation({json.dumps(fixture)})));"
    )
    html = json.loads(subprocess.run(["node"], input=script, check=True, capture_output=True, text=True).stdout)
    assert "high" in html
    assert "object severity" in html
    assert "[object Object]" not in html


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
    for value in ["fixture-model", "stream", "Options", "/chat", "system", "developer", "user"]:
        assert value.lower() in html.lower()
    assert "system &lt;safe&gt;" in html
    assert "secret" not in html
    assert "Final response was empty" in html
    assert "No model output captured" not in html


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
    for field in ["cookie", "set-cookie", "private-key"]:
        assert field not in html.lower()


def test_trace_model_chat_runtime_keeps_full_human_prompt() -> None:
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
    assert "y" * 1000 in html
    assert "oversized_key_239" not in html


def test_trace_model_chat_runtime_keeps_repeated_human_messages() -> None:
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
    assert len(html) > 24000
    assert large[-100:] in html
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


def test_trace_sanitizer_keeps_accounting_metrics_and_model_thinking_expandable() -> None:
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
        "prompt_budget_tokens": 24000,
        "estimated_tokens": 342,
        "token_saving": {"compact_output_tokens_avoided_est": 12},
    }
    script = f"let traceRevealRedactedDetails=false;{redact}{sanitizer}console.log(JSON.stringify(traceSanitizeValue({json.dumps(fixture)})));"
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    sanitized = json.loads(result.stdout)
    assert sanitized == fixture
    assert "trace-thinking" in DASHBOARD_HTML
    assert "Thinking / reasoning" in DASHBOARD_HTML
    assert "model.thinking" in DASHBOARD_HTML
