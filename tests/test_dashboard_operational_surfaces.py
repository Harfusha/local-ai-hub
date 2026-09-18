from local_ai_hub.dashboard import DASHBOARD_HTML


def test_operations_views_name_distinct_records_and_trace_availability() -> None:
    assert "Live scheduler work" in DASHBOARD_HTML
    assert "Request history" in DASHBOARD_HTML
    assert "Trace availability" in DASHBOARD_HTML
    assert "Agent task runs" in DASHBOARD_HTML
    assert "function requestTraceAvailability(request)" in DASHBOARD_HTML


def test_recent_request_table_reserves_trace_and_duration_columns() -> None:
    assert ".work-panel-3 th:nth-child(8){width:12%}" in DASHBOARD_HTML
    assert ".work-panel-3 th:nth-child(9){width:7%}" in DASHBOARD_HTML
    assert ".work-panel-3 td:nth-child(8),.work-panel-3 td:nth-child(9){white-space:nowrap" in DASHBOARD_HTML


def test_projects_and_bundles_expose_canonical_identity_and_readiness() -> None:
    assert "Repository identity" in DASHBOARD_HTML
    assert "Group worktrees" in DASHBOARD_HTML
    assert "function projectIdentity(project)" in DASHBOARD_HTML
    assert "Bundle readiness" in DASHBOARD_HTML
    assert "Index contents" in DASHBOARD_HTML


def test_rag_reliability_and_events_have_operational_filters() -> None:
    assert "Search RAG workspaces" in DASHBOARD_HTML
    assert "Workspace identity" in DASHBOARD_HTML
    assert "Operational severity" in DASHBOARD_HTML
    assert "Failure trend" in DASHBOARD_HTML
    assert "Event severity" in DASHBOARD_HTML
    assert "Event source" in DASHBOARD_HTML


def test_live_events_with_trace_id_link_to_trace_inspector() -> None:
    source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function renderEvents(events=liveEvents)") : DASHBOARD_HTML.index(
            "async function pollEvents()"
        )
    ]
    assert "traceId=e.trace_id" in source
    assert "traceAttr=traceId?" in source
    assert "data-trace-id" in source
    assert "data-detail=\"${id}\"" in source


def test_destructive_controls_describe_scope_and_impact() -> None:
    assert "Restart hub service" in DASHBOARD_HTML
    assert "Purge expired cache" in DASHBOARD_HTML
    assert "Scope and impact" in DASHBOARD_HTML
    assert "function openControlConfirmation" in DASHBOARD_HTML


def test_reliability_summary_footer_padding_and_severity_contract() -> None:
    assert 'class="reliability-footer"' in DASHBOARD_HTML
    assert 'id="reliabilityTrend"' in DASHBOARD_HTML
    assert 'id="reliabilityAction"' in DASHBOARD_HTML
    footer_idx = DASHBOARD_HTML.index('class="reliability-footer"')
    trend_idx = DASHBOARD_HTML.index('id="reliabilityTrend"')
    action_idx = DASHBOARD_HTML.index('id="reliabilityAction"')
    assert footer_idx < trend_idx < action_idx
    # Assert active crash rather than any historical crash determines attention severity
    assert "activeCrash" in DASHBOARD_HTML
    assert "failures||activeCrash?'attention':restarts?'warning':'healthy'" in DASHBOARD_HTML


def test_operational_severity_resolve_errors_action() -> None:
    assert 'id="resolveErrorsBtn"' in DASHBOARD_HTML
    assert 'id="resolveAllErrorsBtn"' in DASHBOARD_HTML
    assert 'function renderResolveErrorsModal(r)' in DASHBOARD_HTML
    assert "/api/maintenance/resolve_errors" in DASHBOARD_HTML
    assert "type==='resolve_errors'" in DASHBOARD_HTML
    footer_idx = DASHBOARD_HTML.index('class="reliability-footer"')
    trend_idx = DASHBOARD_HTML.index('id="reliabilityTrend"')
    resolve_idx = DASHBOARD_HTML.index('id="resolveErrorsBtn"')
    action_idx = DASHBOARD_HTML.index('id="reliabilityAction"')
    assert footer_idx < trend_idx < resolve_idx < action_idx



def test_dashboard_ux_refinements_and_empty_states() -> None:
    # 1. Control popover & buttons
    assert "Pause live events" in DASHBOARD_HTML
    assert ".control-popover .tiny.muted" in DASHBOARD_HTML
    # 2. Toolbar select dark theme
    assert ".toolbar select" in DASHBOARD_HTML
    # 3. Live events header row
    assert 'class="event-header"' in DASHBOARD_HTML
    assert "Action / Stage" in DASHBOARD_HTML
    # 4. Styled empty table state
    assert "No active items recorded" in DASHBOARD_HTML
    # 5. Worktrees toolbar
    assert 'id="worktreeRoot" placeholder="Repository root"' in DASHBOARD_HTML
    # 6. Reliability tab auto-tail
    assert "if(tabId==='reliability')loadLogsTail();" in DASHBOARD_HTML
    # 7. Bundles table wrap
    assert '<div class="table-wrap"><table><thead><tr><th>Repository identity</th>' in DASHBOARD_HTML
