"""Tests for modern dashboard assets, CSP strictness, and host diagnostics (HUB-093, HUB-094, HUB-100)."""

from __future__ import annotations

import json
import re
from io import BytesIO

from local_ai_hub import http_server
from local_ai_hub.dashboard_frontend import (
    LEGACY_PAGES,
    dashboard_frontend_asset,
    dashboard_frontend_html,
    inspect_agent_hosts,
)


def test_static_dashboard_bundle_is_packaged_and_uses_only_external_assets():
    html = dashboard_frontend_html()
    css = dashboard_frontend_asset("app.css")
    script = dashboard_frontend_asset("app.js")

    assert css is not None and css[0] == "text/css; charset=utf-8"
    assert script is not None and script[0] == "text/javascript; charset=utf-8"
    assert '<link rel="stylesheet" href="/dashboard-assets/app.css">' in html
    assert '<script type="module" src="/dashboard-assets/app.js"></script>' in html
    assert not re.search(
        r"<script(?:\s|>)",
        html.replace('<script type="module" src="/dashboard-assets/app.js"></script>', ""),
    )
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
    assert "article.append(title, metadata, outcome)" in script_text
    assert "timeline does not show current runtime health or request traces" in script_text


def test_new_sections_preserve_all_eleven_legacy_dashboard_destinations():
    html = dashboard_frontend_html()
    legacy_navigation = html.split('<div class="legacy-grid" id="legacy-pages">', 1)[1].split(
        "</div>", 1
    )[0]

    assert len(LEGACY_PAGES) == 11
    for slug, label, section in LEGACY_PAGES:
        expected_href = f'/dashboard#{slug}'
        assert expected_href in legacy_navigation
        assert label in legacy_navigation
        assert f'data-section="{section}"' in legacy_navigation


def test_inspect_agent_hosts_returns_truthful_codex_and_antigravity_states():
    result = inspect_agent_hosts()
    assert result["success"] is True
    assert isinstance(result.get("hosts"), list)
    host_ids = {h["host_id"] for h in result["hosts"]}
    assert "codex" in host_ids
    assert "antigravity" in host_ids

    for h in result["hosts"]:
        assert "status" in h
        assert h["status"] in {"ready", "degraded", "not_installed", "stale"}
        assert "remediation" in h
        if not h.get("detected_cli"):
            assert h["status"] == "not_installed"


def test_visibility_aware_polling_contract_in_app_js():
    _mime, script = dashboard_frontend_asset("app.js")
    script_text = script.decode("utf-8")

    assert 'document.addEventListener("visibilitychange"' in script_text
    assert 'window.addEventListener("focus"' in script_text
    assert "AbortController" in script_text
    assert "scheduleNextPoll" in script_text
    assert "document.hidden" in script_text


def test_dashboard_next_handler_returns_strict_csp(monkeypatch):
    sent_headers: dict[str, str] = {}
    output = BytesIO()

    class MockApp:
        config = {
            "monitoring": {"dashboard_enabled": True},
            "features": {"dashboard": True},
        }

    monkeypatch.setattr(http_server, "APP", MockApp())

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.wfile = output
    handler.client_address = ("127.0.0.1", 54321)
    handler.headers = {}
    handler.path = "/dashboard/next"
    handler.command = "GET"
    handler._telemetry_finished = False

    def send_response(code):
        handler._code = code

    def send_header(name, value):
        sent_headers[name] = value

    def end_headers():
        pass

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    handler._reject_identity_fields = lambda *a, **kw: True
    handler._finish_static_response = lambda *a, **kw: None

    handler.do_GET()

    assert handler._code == 200
    assert "style-src 'self'" in sent_headers.get("Content-Security-Policy", "")
    assert "script-src 'self'" in sent_headers.get("Content-Security-Policy", "")
    assert "'unsafe-inline'" not in sent_headers.get("Content-Security-Policy", "")
    assert b"<!doctype html>" in output.getvalue()


def test_dashboard_assets_endpoint_serves_css_and_js(monkeypatch):
    for asset_name, expected_content_type in [
        ("app.css", "text/css; charset=utf-8"),
        ("app.js", "text/javascript; charset=utf-8"),
    ]:
        sent_headers: dict[str, str] = {}
        output = BytesIO()

        class MockApp:
            config = {
                "monitoring": {"dashboard_enabled": True},
                "features": {"dashboard": True},
            }

        monkeypatch.setattr(http_server, "APP", MockApp())

        handler = http_server.Handler.__new__(http_server.Handler)
        handler.wfile = output
        handler.client_address = ("127.0.0.1", 54321)
        handler.headers = {}
        handler.path = f"/dashboard-assets/{asset_name}"
        handler.command = "GET"
        handler._telemetry_finished = False

        def send_response(code):
            handler._code = code

        def send_header(name, value):
            sent_headers[name] = value

        def end_headers():
            pass

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers
        handler._reject_identity_fields = lambda *a, **kw: True
        handler._finish_static_response = lambda *a, **kw: None

        handler.do_GET()

        assert handler._code == 200
        assert sent_headers.get("Content-Type") == expected_content_type
        assert len(output.getvalue()) > 0


def test_agent_hosts_endpoint_returns_json(monkeypatch):
    sent_headers: dict[str, str] = {}
    output = BytesIO()

    class MockApp:
        config = {}

    monkeypatch.setattr(http_server, "APP", MockApp())

    handler = http_server.Handler.__new__(http_server.Handler)
    handler.wfile = output
    handler.client_address = ("127.0.0.1", 54321)
    handler.headers = {}
    handler.path = "/api/agent/hosts"
    handler.command = "GET"
    handler._telemetry_finished = False

    def send_response(code):
        handler._code = code

    def send_header(name, value):
        sent_headers[name] = value

    def end_headers():
        pass

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    handler._reject_identity_fields = lambda *a, **kw: True
    handler._finish_static_response = lambda *a, **kw: None

    handler.do_GET()

    assert handler._code == 200
    payload = json.loads(output.getvalue().decode("utf-8"))
    assert payload["success"] is True
    assert isinstance(payload["hosts"], list)

