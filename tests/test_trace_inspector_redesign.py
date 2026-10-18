from __future__ import annotations

import subprocess
from shutil import which

from local_ai_hub.dashboard import DASHBOARD_HTML


def test_trace_metric_row_marks_unrecorded_values_and_formats_recorded_values():
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    start = DASHBOARD_HTML.index("function traceMetricRow(")
    end = DASHBOARD_HTML.index("\n}", start) + 2
    source = DASHBOARD_HTML[start:end]
    script = (
        source
        + "console.log(JSON.stringify([traceMetricRow({available:false}),traceMetricRow({available:true,input_tokens:12,output_tokens:7,cache_hits:1,cache_hit_rate:0.5,avoided_cloud_tokens:19})]));"
    )
    result = subprocess.run(
        ["node"], input=script, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    import json

    missing, recorded = json.loads(result.stdout)
    assert missing.count("nezaznamenané") == 5
    assert all(value in recorded for value in ("12", "7", "1", "50.0%", "19"))


def test_trace_inspector_has_single_header_copyable_input_output_and_collapsed_details():
    render_start = DASHBOARD_HTML.index("function renderTraceDetail(d)")
    render_end = DASHBOARD_HTML.index("function setTraceView(view)", render_start)
    render = DASHBOARD_HTML[render_start:render_end]
    assert "traceMainContent('Input'" in render
    assert "traceMainContent('Output'" in render
    assert "traceMetricRow" in render
    assert 'data-trace-copy="${field}"' in DASHBOARD_HTML
    assert "traceMainContent('Input','input',tracePrimaryInput(model.input))" in render
    assert "traceMainContent('Output','output',model.output)" in render
    assert "trace-inspector-context" not in render
    assert "data-trace-reveal" not in render
    assert 'id="traceTechnicalDetails"' in render


def test_trace_primary_input_only_removes_top_level_settings():
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    start = DASHBOARD_HTML.index("function tracePrimaryInput(")
    end = DASHBOARD_HTML.index("function traceMainContent(", start)
    source = DASHBOARD_HTML[start:end]
    script = (
        source
        + "const payload={prompt:'show cache rate',metadata:{settings:'user content'},project:'demo',settings:{model:'local'}};"
        + "console.log(JSON.stringify([tracePrimaryInput(payload),traceTechnicalSettings(payload)]));"
    )
    result = subprocess.run(
        ["node"], input=script, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    import json

    primary, settings = json.loads(result.stdout)
    assert primary == {"prompt": "show cache rate", "metadata": {"settings": "user content"}}
    assert settings == {"project": "demo", "settings": {"model": "local"}}


def test_trace_project_label_uses_raw_session_root_fallback():
    model_source = DASHBOARD_HTML[
        DASHBOARD_HTML.index("function traceDisplayModel(detail)") : DASHBOARD_HTML.index(
            "function traceAvailability("
        )
    ]
    assert "root:rawSession.root" in model_source


def test_trace_display_redacts_credentials_and_preserves_ordinary_content():
    assert which("node"), "Dashboard JavaScript tests require Node.js"
    sanitizer_start = DASHBOARD_HTML.index("function traceSecretString(")
    sanitizer_end = DASHBOARD_HTML.index("\nfunction traceRecorded(", sanitizer_start)
    script = (
        DASHBOARD_HTML[sanitizer_start:sanitizer_end]
        + "const payload={prompt:'Show my cache hit rate; used 18 tokens',api_"
        + "key:'api-" + "secret-value',"
        + "nested:{access_" + "token:'access-" + "secret-value',note:'Bearer event-" + "secret',db_"
        + "pass" + "word:'database-" + "secret',GITHUB_" + "TOKEN:'github-" + "secret'}};"
        + "console.log(JSON.stringify(traceSanitizeValue(payload)));"
    )
    result = subprocess.run(
        ["node"], input=script, check=False, capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr

    import json

    rendered = json.loads(result.stdout)
    assert rendered["prompt"] == "Show my cache hit rate; used 18 tokens"
    assert rendered["api_key"] == "[redacted]"
    assert rendered["nested"]["access_token"] == "[redacted]"
    assert rendered["nested"]["note"] == "Bearer [redacted]"
    assert rendered["nested"]["db_" + "password"] == "[redacted]"
    assert rendered["nested"]["GITHUB_TOKEN"] == "[redacted]"


def test_detailed_trace_preserves_complete_payload_and_token_metrics():
    from local_ai_hub.http_server import Handler

    captured = Handler._safe_debug_trace_request(
        {
            "prompt": "Explain cache hit rate and token savings",
            "token_usage": {"input_tokens": 15, "output_tokens": 9},
            "api_key": "api-secret-value",
            "headers": {"Authorization": "Bearer access-secret-value"},
            "root": r"C:\\work\\sample-project",
        }
    )
    text = str(captured)
    assert "Explain cache hit rate and token savings" in text
    assert "input_tokens" in text and "15" in text
    assert "output_tokens" in text and "9" in text
    assert "api-secret-value" in text
    assert "access-secret-value" in text
    assert "[redacted]" not in text
    assert captured["root"] == r"C:\\work\\sample-project"


def test_enabled_trace_store_preserves_complete_payload_and_token_usage(tmp_path):
    import json

    from local_ai_hub.debug_traces import DebugTraceStore

    store = DebugTraceStore({"server": {"state_dir": str(tmp_path)}, "debug_traces": {"enabled": True}})
    trace_id = store.start(kind="api_request",  action="/api/test")
    store.update(
        trace_id,
        request={"prompt": "Show my cache hit rate", "input_tokens": 8, "root": r"C:\\Users\\private\\project", "api_key": "stored-secret"},
        output={"answer": "Used 8 tokens", "access_token": "stored-access-secret"},
    )
    store.event(trace_id, "model_request", {"prompt": "Show my cache hit rate", "token_usage": 8, "authorization": "Bearer event-secret"})
    detail = store.detail(trace_id, full_payload=True)
    stored = json.dumps(detail, ensure_ascii=False)
    assert "Show my cache hit rate" in stored
    assert "Used 8 tokens" in stored
    assert detail["session"]["request"]["root"] == r"C:\\Users\\private\\project"
    assert '"input_tokens": 8' in stored
    assert '"token_usage": 8' in stored
    assert "stored-secret" in stored
    assert "stored-access-secret" in stored
    assert "event-secret" in stored
    assert "[redacted]" not in stored
