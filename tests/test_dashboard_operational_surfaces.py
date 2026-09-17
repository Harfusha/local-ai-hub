from local_ai_hub.dashboard import DASHBOARD_HTML


def test_operations_views_name_distinct_records_and_trace_availability() -> None:
    assert "Live scheduler work" in DASHBOARD_HTML
    assert "Request history" in DASHBOARD_HTML
    assert "Trace availability" in DASHBOARD_HTML
    assert "Agent task runs" in DASHBOARD_HTML
    assert "function requestTraceAvailability(request)" in DASHBOARD_HTML


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
