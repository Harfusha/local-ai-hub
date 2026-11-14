from __future__ import annotations

import re
from io import BytesIO
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.dashboard_frontend import (
    LEGACY_PAGES,
    dashboard_frontend_asset,
    dashboard_frontend_html,
)


def test_static_dashboard_bundle_is_packaged_and_uses_only_external_assets():
    html = dashboard_frontend_html()
    css = dashboard_frontend_asset("app.css")
    script = dashboard_frontend_asset("app.js")

    assert css is not None and css[0] == "text/css; charset=utf-8"
    assert script is not None and script[0] == "text/javascript; charset=utf-8"
    assert '<link rel="stylesheet" href="/dashboard-assets/app.css">' in html
    assert '<script type="module" src="/dashboard-assets/app.js"></script>' in html
    assert not re.search(r"<script(?:\s|>)", html.replace(
        '<script type="module" src="/dashboard-assets/app.js"></script>', ""
    ))
    assert "https://" not in html + css[1].decode("utf-8") + script[1].decode("utf-8")
    assert "innerHTML" not in script[1].decode("utf-8")


def test_task_records_disclose_returned_fields_as_text():
    html = dashboard_frontend_html()
    _mime, script = dashboard_frontend_asset("app.js")
    script_text = script.decode("utf-8")

    assert "Expand a task to inspect every field returned by the stored record." in html
    assert 'document.createElement("details")' in script_text
    assert 'summary.textContent = "Show stored task details"' in script_text
    assert "payload.textContent = JSON.stringify(record, null, 2)" in script_text


def test_telemetry_timeline_is_user_triggered_paged_and_historical():
    html = dashboard_frontend_html()
    _mime, script = dashboard_frontend_asset("app.js")
    script_text = script.decode("utf-8")

    assert 'id="load-telemetry-timeline"' in html
    assert 'id="load-older-telemetry"' in html
    assert 'new URLSearchParams({ limit: "50" })' in script_text
    assert 'params.set("before_id", String(timelineCursor))' in script_text
    assert 'article.append(title, metadata, outcome)' in script_text
    assert "timeline does not show current runtime health or request traces" in script_text


def test_new_sections_preserve_all_eleven_legacy_dashboard_destinations():
    html = dashboard_frontend_html()
    legacy_navigation = html.split('<div class="legacy-grid" id="legacy-pages">', 1)[1].split(
        "</div>", 1
    )[0]
    destinations = re.findall(r'href="/dashboard#([a-z0-9_-]+)"', legacy_navigation)

    assert len(LEGACY_PAGES) == 11
    assert len(destinations) == 11
    assert set(destinations) == {page_id for page_id, _label, _section in LEGACY_PAGES}
    assert {section for _page_id, _label, section in LEGACY_PAGES} == {
        "overview", "projects", "agents", "tasks", "models", "diagnostics", "settings",
    }
    for section in (
        "overview", "projects", "agents", "tasks", "models", "diagnostics", "settings",
    ):
        assert f'data-section="{section}"' in html


def test_frontend_asset_route_is_exact_allow_list():
    assert dashboard_frontend_asset("../app.js") is None
    assert dashboard_frontend_asset("index.html") is None
    assert dashboard_frontend_asset("app.js/extra") is None


def test_static_dashboard_csp_allows_only_self_hosted_assets():
    handler = http_server.Handler.__new__(http_server.Handler)
    headers = []
    handler.headers = {}
    handler.path = "/dashboard/next"
    handler.send_header = lambda name, value: headers.append((name, value))

    handler._common_headers(html=True, self_hosted_assets=True)

    policy = dict(headers)["Content-Security-Policy"]
    assert "style-src 'self'" in policy
    assert "script-src 'self'" in policy
    assert "unsafe-inline" not in policy


def test_dashboard_asset_handler_serves_only_packaged_allow_list_assets():
    handler = http_server.Handler.__new__(http_server.Handler)
    headers = []
    handler.path = "/dashboard-assets/app.js"
    handler.headers = {}
    handler.wfile = BytesIO()
    handler.close_connection = False
    handler.send_response = lambda status: headers.append(("status", status))
    handler.send_header = lambda name, value: headers.append((name, value))
    handler.end_headers = lambda: None
    handler._finish_static_response = lambda *_args, **_kwargs: None

    assert handler._send_dashboard_frontend_asset("app.js") is True
    assert dict(headers)["Content-Type"] == "text/javascript; charset=utf-8"
    assert b"textContent" in handler.wfile.getvalue()
    assert handler._send_dashboard_frontend_asset("../secrets") is False


def test_new_dashboard_shell_route_keeps_dashboard_feature_gate(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "monitoring": {"dashboard_enabled": True},
        "features": {"dashboard": True},
    }))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/dashboard/next"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: pytest.fail("dashboard shell must remain public")
    handler.responses = []
    handler._send = lambda status, data: handler.responses.append((status, data))
    handler._send_html = lambda status, html, **kwargs: handler.responses.append((status, html, kwargs))

    handler.do_GET()

    assert handler.responses[0][0] == 200
    assert "Local AI Hub" in handler.responses[0][1]
    assert handler.responses[0][2] == {"self_hosted_assets": True}


def test_legacy_dashboard_links_to_the_preview_shell():
    html = http_server._dashboard_html_with_trace_notice()

    assert '<a class="btn" href="/dashboard/next" aria-label="Open the new dashboard preview">New dashboard preview</a>' in html
    assert 'data-tab="overview"' in html
    assert 'data-tab="events"' in html


def test_responsive_shell_has_keyboard_and_screen_reader_basics():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")
    styles = dashboard_frontend_asset("app.css")[1].decode("utf-8")

    assert 'class="skip-link" href="#main-content"' in html
    assert 'aria-controls="primary-nav"' in html
    assert 'id="primary-nav"' in html
    assert 'role="status" aria-live="polite"' in html
    assert "event.key === \"Escape\"" in script
    assert "menuToggle.focus()" in script
    assert 'setAttribute("aria-label", open ? "Close navigation" : "Open navigation")' in script
    assert "font-size: 15px" in styles
    assert "@media (max-width: 900px)" in styles
    assert "@media (max-width: 680px)" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert ".nav-item { min-height: 46px" in styles
    assert ".menu-toggle { display: none; width: 44px; height: 44px" in styles
    assert 'tabindex="-1"' in html
    assert "--focus: #f7d49a" in styles
    assert "button:focus-visible, a:focus-visible" in styles
    assert "overflow-wrap: anywhere" in styles
    assert ".action-button { min-height: 44px" in styles


def test_overview_separates_current_api_observation_from_unknown_resources():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")

    assert "Current check · Hub API" in html
    assert 'id="checked-at"' in html
    assert "Project health not loaded" in html
    assert "Task state not loaded" in html
    assert "Open Diagnostics" in html
    assert "The current status response reports a degraded dependency." in script
    assert "Other resource health is unknown." in script
    assert 'value.textContent = "Unknown"' in script
    assert 'fetch("/api/live/status?light=1"' in script
    assert 'payload.snapshot_warming === true' in script
    assert 'payload.snapshot_stale === true' in script
    assert "This is the last cached status snapshot, not a current health measurement." in script


def test_projects_view_scopes_requests_and_uses_text_nodes_for_api_data():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")

    assert 'id="project-root" name="root" type="text" required' in html
    assert 'id="project-operation-status" role="status" aria-live="polite"' in html
    assert 'const windowsDrive = /^[A-Za-z]:[\\\\/]/.test(root)' in script
    assert 'const uncPath = root.startsWith("\\\\\\\\")' in script
    assert 'const posixPath = root.startsWith("/")' in script
    assert "/api/preprocess/status?root=${encodeURIComponent(root)}" in script
    assert "item.root === root" in script
    assert 'JSON.stringify({ root, action, ...(action === "unregister" ? { purge_data: false } : {}) })' in script
    assert "Refresh indexes for this exact root?" in script
    assert "Unregister this root? Source files stay untouched; cache purge is disabled." in script
    assert "let projectOperationInFlight = false" in script
    assert "button.disabled = true" in script
    assert "button.disabled = false" in script
    assert "description.textContent =" in script
    assert "innerHTML" not in script


def test_tasks_view_is_root_scoped_and_labels_state_as_stored_evidence():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")

    assert 'id="tasks-root" name="root" type="text" required' in html
    assert 'href="/dashboard#coordination"' in html
    assert "/api/agent-state/tasks?${query}" in script
    assert '`root=${encodeURIComponent(root)}&limit=50&include_stale=false`' in script
    assert 'projectRequest(`/api/coord/worktrees?root=${encodeURIComponent(root)}`' in script
    assert 'status.textContent = `Recorded state:' in script
    assert "These records do not establish completion." in script
    assert "description.textContent =" in script
    assert "innerHTML" not in script


def test_unmigrated_sections_point_to_current_pages_without_claiming_checks():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")

    assert 'id="section-notice"' in html
    assert 'id="section-notice" aria-labelledby="section-notice-title" hidden' in html
    assert "this preview yet" in script
    assert "has not checked or changed its configuration" in script
    assert 'sectionNotice.hidden = migrated' in script
    for section in ("agents", "models", "diagnostics", "settings"):
        assert f'data-section="{section}"' in html


def test_diagnostics_view_uses_aggregate_stats_and_labels_estimates():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")

    assert 'id="diagnostics-view"' in html
    assert 'name="root" type="text" autocomplete="off"' in html
    assert "/api/telemetry/endpoint-stats?${params}" in script
    assert 'new URLSearchParams({ scope: "active", buckets: "1" })' in script
    assert "Estimated from fixed histogram buckets" in script
    assert "diagnosticsRecords.textContent = JSON.stringify" in script
    assert "No request body or prompt content was requested." in script
    assert 'href="/dashboard#events"' in html


def test_models_view_is_inventory_only_and_never_claims_runtime_or_training():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")

    assert 'id="models-view"' in html
    assert 'id="load-models" type="button"' in html
    assert 'projectRequest("/api/models"' in script
    assert "Inventory owner:" in script
    assert "Runtime and quality state remain unknown." in script
    assert "does not prove routing, residency, VRAM, or inference quality." in html
    assert "No training or model pull is available from this preview." in html
    assert "innerHTML" not in script


def test_settings_preview_reads_only_redacted_config_and_does_not_mutate():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")

    assert 'id="settings-view"' in html
    assert "Secret values are redacted by the existing API." in html
    assert 'projectRequest("/api/config"' in script
    assert 'config: result.config' in script
    assert "Redacted configuration snapshot loaded. No values were changed." in script
    assert "does not edit, import, export, or restart the Hub." in html
    assert 'href="/dashboard#config"' in html


def test_agents_view_checks_agent_host_readiness_and_preserves_policy():
    html = dashboard_frontend_html()
    script = dashboard_frontend_asset("app.js")[1].decode("utf-8")

    assert 'id="agents-view"' in html
    assert 'id="load-agents" type="button"' in html
    assert 'projectRequest("/api/status?detail=agent_state"' in script
    assert 'projectRequest("/api/capabilities"' in script
    assert "Agent OS Coordination & State" in script
    assert "Antigravity / Codex Skills & Hook" in script
    assert "MCP Client Readiness" in script
    assert "innerHTML" not in script



def test_dashboard_legacy_alias_serves_legacy_dashboard(monkeypatch):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={
        "monitoring": {"dashboard_enabled": True},
        "features": {"dashboard": True},
    }))
    handler = http_server.Handler.__new__(http_server.Handler)
    handler.path = "/dashboard/legacy"
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {"Content-Type": "application/json"}
    handler._begin_trace = lambda _path: None
    handler._require_authorized = lambda: pytest.fail("dashboard legacy route must remain public")
    handler.responses = []
    handler._send = lambda status, data: handler.responses.append((status, data))
    handler._send_html = lambda status, html, **kwargs: handler.responses.append((status, html, kwargs))

    handler.do_GET()

    assert handler.responses[0][0] == 200
    assert "New dashboard preview" in handler.responses[0][1]
    assert "/dashboard/legacy" in http_server.MONITOR_PATHS

