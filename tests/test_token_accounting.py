from __future__ import annotations

import json
from pathlib import Path

from local_ai_hub.telemetry import TelemetryStore
from local_ai_hub.token_accounting import finalize_tool_accounting, measure_savings, pop_accounting


def test_telemetry_keeps_measured_provider_cache_reads_as_numeric_metadata():
    event = TelemetryStore._clean_event({
        "action": "local_ai_task",
        "task_type": "review",
        "input_tokens": 120,
        "cache_read_tokens": 80,
        "output_tokens": 25,
    })

    assert event["action"] == "local_ai_task"
    assert event["task_type"] == "review"
    assert event["cache_read_tokens"] == 80


def test_telemetry_reports_provider_cache_reads_by_action_and_task_type(tmp_path: Path):
    store = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.01)
    try:
        store.record(
            event_type="inference",
            action="local_ai_task",
            task_type="review",
            model="provider-a",
            input_tokens=120,
            cache_read_tokens=80,
            output_tokens=25,
        )
        assert store.flush()

        summary = store.summary(scope="process")
        report = store.report(scope="process")
        tail = store.tail(1)

        assert summary["provider_cache_read_tokens"] == 80
        assert tail[0]["cache_read_tokens"] == 80
        assert report["provider_token_usage"] == [{
            "action": "local_ai_task", "task_type": "review", "model": "provider-a",
            "input_tokens": 120, "cache_read_tokens": 80, "output_tokens": 25,
        }]
    finally:
        store.close()


def test_savings_signals_do_not_double_count_overlapping_input_reductions():
    value = {
        "token_saving": {
            "delegated_cloud_context_tokens_avoided_est": 1200,
            "compact_output_tokens_avoided_est": 300,
        },
        "nested": {"original_estimated_tokens": 1000, "estimated_tokens": 200},
    }
    measured = measure_savings(value)
    # 1200 delegated-context and the structural context baseline overlap. The
    # response-compaction delta is diagnostic here and is not added on top of the
    # upstream source baseline, otherwise the same context chain would be counted twice.
    assert measured["gross_input_tokens_avoided_est"] == 1200
    assert measured["gross_output_tokens_avoided_est"] == 300
    assert measured["gross_cloud_tokens_avoided_est"] == 1200
    assert measured["savings_breakdown"] == {"delegated_context": 1200}


def test_tool_accounting_subtracts_agent_call_and_read_cost():
    response = {"success": True, "summary": "done"}
    event = finalize_tool_accounting(
        tool_name="local_ai_repo",
        arguments={"action": "context", "root": "C:/repo", "query": "cache invalidation"},
        response=response,
        measured={
            "gross_cloud_tokens_avoided_est": 2000,
            "gross_input_tokens_avoided_est": 1800,
            "gross_output_tokens_avoided_est": 200,
            "savings_breakdown": {"context_compaction": 1800, "response_compaction": 200},
        },
        schema_tokens_est=150,
    )
    assert event["agent_tool_request_tokens_est"] > 0
    assert event["agent_tool_response_tokens_est"] > 0
    assert event["net_cloud_token_delta_est"] == 2000 - event["agent_protocol_tokens_est"]
    assert event["net_after_schema_token_delta_est"] == event["net_cloud_token_delta_est"] - 150


def test_tool_accounting_attributes_response_budget_without_source_text():
    event = finalize_tool_accounting(
        tool_name="local_ai_repo",
        arguments={"action": "search", "root": "C:/repo", "query": "private-secret"},
        response={
            "success": True,
            "summary": "bounded",
            "response_budget": {"requested_tokens": 700, "truncated": True},
            "cache_hit": True,
        },
        measured={"raw_response_tokens_est": 5000, "projected_response_tokens_est": 700},
    )

    assert event["operation_category"] == "search"
    assert event["raw_response_tokens_est"] == 5000
    assert event["projected_response_tokens_est"] == 700
    assert event["projected_response_saved_tokens_est"] == 4300
    assert event["response_budget_requested_tokens"] == 700
    assert event["response_budget_truncated"] is True
    assert event["cache_outcome"] == "cache_hit"
    assert "private-secret" not in str(event)


def test_private_accounting_never_reaches_agent_payload():
    value = {
        "success": True,
        "summary": "ok",
        "_token_accounting": {
            "gross_input_tokens_avoided_est": 900,
            "gross_cloud_tokens_avoided_est": 900,
            "savings_breakdown": {"deterministic_outline": 900},
        },
    }
    clean, measured = pop_accounting(value)
    assert "_token_accounting" not in clean
    assert measured["gross_cloud_tokens_avoided_est"] == 900


def test_telemetry_reports_gross_protocol_net_and_breakdown(tmp_path: Path):
    store = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_tool_accounting({
            "tool": "local_ai_repo",
            "tenant": "t",
            "agent": "codex",
            "gross_cloud_tokens_avoided_est": 1800,
            "gross_input_tokens_avoided_est": 1000,
            "gross_output_tokens_avoided_est": 800,
            "input_savings_source": "deterministic_outline",
            "output_savings_source": "response_compaction",
            "agent_tool_request_tokens_est": 40,
            "agent_tool_response_tokens_est": 160,
            "agent_protocol_tokens_est": 200,
            "tool_schema_tokens_est": 120,
            "net_cloud_token_delta_est": 1600,
            "cloud_token_overhead_est": 0,
            "net_after_schema_token_delta_est": 1480,
            "schema_adjusted_overhead_est": 0,
            "local_compute_tokens_avoided_est": 500,
            "savings_breakdown": {"deterministic_outline": 1000, "response_compaction": 800},
        })
        assert store.flush()
        summary = store.summary(scope="process")
        assert summary["gross_cloud_tokens_avoided_est"] == 1800
        assert summary["agent_protocol_tokens_est"] == 200
        assert summary["agent_tool_request_tokens_est"] == 40
        assert summary["agent_tool_response_tokens_est"] == 160
        assert summary["net_cloud_token_delta_est"] == 1600
        assert summary["net_after_schema_token_delta_est"] == 1480
        assert summary["local_compute_tokens_avoided_est"] == 500
        assert summary["token_savings_breakdown"]["deterministic_outline"] == 1000
    finally:
        store.close()


def test_telemetry_reports_cache_domains_separately(tmp_path: Path):
    store = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.01)
    try:
        store.record(event_type="inference", action="delegate:review", cache_hit=True, coalesced=False, success=True)
        store.record(event_type="inference", action="delegate:review", cache_hit=False, coalesced=False, success=True)
        store.record_http(action="/api/repo/code-index", cache_hit=True, cache_layer="workspace", success=True)
        store.record_http(action="/api/repo/search", cache_hit=False, cache_layer="workspace-miss", success=True)
        store.record_http(action="/api/command", cache_hit=True, cache_layer="", success=True)
        assert store.flush()

        domains = store.summary(scope="process")["cache_domains"]

        assert domains["generation"] == {"events": 2, "hits": 1, "coalesced": 0, "hit_rate": 0.5}
        assert domains["repository"] == {"events": 2, "hits": 1, "coalesced": 0, "hit_rate": 0.5}
        assert domains["command"] == {"events": 1, "hits": 1, "coalesced": 0, "hit_rate": 1.0}
    finally:
        store.close()


def test_telemetry_prices_input_and_output_savings_separately(tmp_path: Path):
    store = TelemetryStore(
        tmp_path,
        enabled=True,
        cloud_input_token_cost_usd_per_million=2.0,
        cloud_output_token_cost_usd_per_million=8.0,
        flush_interval_seconds=0.01,
    )
    try:
        store.record_tool_accounting({
            "tool": "local_ai_repo",
            "gross_cloud_tokens_avoided_est": 1500,
            "gross_input_tokens_avoided_est": 1000,
            "gross_output_tokens_avoided_est": 500,
            "agent_tool_request_tokens_est": 100,
            "agent_tool_response_tokens_est": 200,
            "agent_protocol_tokens_est": 300,
            "net_cloud_token_delta_est": 1200,
        })
        assert store.flush()
        summary = store.summary(scope="process")
        assert summary["estimated_input_savings_usd"] == 0.0016
        assert summary["estimated_output_savings_usd"] == 0.0032
        assert summary["estimated_savings_usd"] == 0.0048
        assert summary["cloud_input_token_cost_usd_per_million"] == 2.0
        assert summary["cloud_output_token_cost_usd_per_million"] == 8.0
    finally:
        store.close()


def test_telemetry_does_not_price_overlapping_output_baseline_twice(tmp_path: Path):
    store = TelemetryStore(
        tmp_path,
        enabled=True,
        cloud_input_token_cost_usd_per_million=2.0,
        cloud_output_token_cost_usd_per_million=8.0,
        flush_interval_seconds=0.01,
    )
    try:
        store.record_tool_accounting({
            "tool": "local_ai_repo",
            "gross_cloud_tokens_avoided_est": 1000,
            "gross_input_tokens_avoided_est": 1000,
            "gross_output_tokens_avoided_est": 300,
            "agent_tool_request_tokens_est": 100,
            "agent_tool_response_tokens_est": 200,
            "agent_protocol_tokens_est": 300,
            "net_cloud_token_delta_est": 700,
        })
        assert store.flush()
        summary = store.summary(scope="process")
        assert summary["estimated_input_savings_usd"] == 0.0016
        assert summary["estimated_output_savings_usd"] == -0.0008
        assert summary["estimated_savings_usd"] == 0.0008
    finally:
        store.close()


def test_noncurrent_telemetry_schema_is_rebuilt(tmp_path: Path):
    import sqlite3

    path = tmp_path / "telemetry.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)")
    con.execute("INSERT INTO events(id, marker) VALUES(1, 'discard-me')")
    con.commit()
    con.close()

    store = TelemetryStore(tmp_path, enabled=True)
    try:
        check = sqlite3.connect(path)
        try:
            tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'") if not row[0].startswith("sqlite_")}
            cols = {row[1] for row in check.execute("PRAGMA table_info(events)")}
            rows = check.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            check.close()
        assert tables == {"events", "errors", "snapshots", "daily_rollups", "process_sessions"}
        assert cols == {"id", *store._EVENT_COLUMNS}
        assert rows == 0
    finally:
        store.close()

def test_tool_accounting_exposes_negative_net_delta_when_tool_costs_more_than_it_saves():
    event = finalize_tool_accounting(
        tool_name="local_ai_status",
        arguments={"detail": "brief"},
        response={"success": True, "online": True},
        measured={"gross_cloud_tokens_avoided_est": 0},
        schema_tokens_est=100,
    )
    assert event["net_cloud_token_delta_est"] < 0
    assert event["cloud_token_overhead_est"] == -event["net_cloud_token_delta_est"]
    assert event["net_after_schema_token_delta_est"] == event["net_cloud_token_delta_est"] - 100
    assert event["schema_adjusted_overhead_est"] == -event["net_after_schema_token_delta_est"]


def test_projection_accounting_does_not_count_internal_runtime_metadata_as_savings():
    from local_ai_hub.token_accounting import account_projection

    raw = {
        "success": True,
        "text": "same",
        "token_saving": {"delegated_cloud_context_tokens_avoided_est": 0},
        "prompt_budget": {"estimated_tokens": 5000, "original_estimated_tokens": 9000},
        "load_duration_ns": 999999,
    }
    projected = {"success": True, "text": "same"}
    clean, measured = pop_accounting(account_projection(raw, projected))
    assert clean == projected
    assert measured["gross_output_tokens_avoided_est"] == 0


def test_telemetry_preserves_signed_net_delta_and_overhead(tmp_path: Path):
    store = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_tool_accounting({
            "tool": "local_ai_status",
            "gross_cloud_tokens_avoided_est": 0,
            "agent_tool_request_tokens_est": 20,
            "agent_tool_response_tokens_est": 30,
            "agent_protocol_tokens_est": 50,
            "tool_schema_tokens_est": 100,
            "net_cloud_token_delta_est": -50,
            "cloud_token_overhead_est": 50,
            "net_after_schema_token_delta_est": -150,
            "schema_adjusted_overhead_est": 150,
        })
        assert store.flush()
        summary = store.summary(scope="process")
        assert summary["net_cloud_token_delta_est"] == -50
        assert summary["cloud_token_overhead_est"] == 50
        assert summary["net_after_schema_token_delta_est"] == -150
        assert summary["schema_adjusted_overhead_est"] == 150
        assert summary["estimated_savings_usd"] < 0
    finally:
        store.close()


def test_json_token_estimator_matches_compact_json_byte_estimate():
    import math
    from local_ai_hub.token_accounting import json_tokens

    value = {"name": "local_ai_repo", "arguments": {"query": "Příliš žluťoučký kůň", "items": list(range(25))}}
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    expected = max(1, math.ceil(len(encoded.encode("utf-8")) / 3.4))
    assert json_tokens(value) == expected


def test_private_accounting_is_authoritative_after_projection():
    value = {
        "success": True,
        "_token_accounting": {
            "gross_cloud_tokens_avoided_est": 777,
            "gross_input_tokens_avoided_est": 700,
            "gross_output_tokens_avoided_est": 77,
            "local_compute_tokens_avoided_est": 55,
            "savings_breakdown": {"context_compaction": 700, "response_compaction": 77},
            "input_savings_source": "context_compaction",
            "output_savings_source": "response_compaction",
        },
        # A projected diagnostic field must not force a second recursive savings scan.
        "original_estimated_tokens": 10000,
        "estimated_tokens": 1,
    }
    clean, measured = pop_accounting(value)
    assert "_token_accounting" not in clean
    assert measured["gross_cloud_tokens_avoided_est"] == 777
    assert measured["gross_input_tokens_avoided_est"] == 700
    assert measured["gross_output_tokens_avoided_est"] == 77


def test_release_gate_rejects_patch_metadata_directory(tmp_path: Path):
    from tools.release_check import _iter_release_hygiene_violations

    (tmp_path / "_local_ai_hub_patch").mkdir()
    (tmp_path / "_local_ai_hub_patch" / "manifest.json").write_text("{}", encoding="utf-8")
    errors = list(_iter_release_hygiene_violations(tmp_path))
    assert any("_local_ai_hub_patch" in item for item in errors)


def test_structural_baseline_is_diagnostic_only():
    # Counterfactual sizes do not prove what a cloud agent would have requested.
    measured = measure_savings({"original_estimated_tokens": 1000, "estimated_tokens": 200})
    assert measured["gross_input_tokens_avoided_est"] == 0
    response = {"context": "x" * 680}
    event = finalize_tool_accounting(
        tool_name="local_ai_repo", arguments={"action": "context", "root": "/repo"},
        response=response, measured=measured,
    )
    assert event["net_cloud_token_delta_est"] == -event["agent_protocol_tokens_est"]


def test_counterfactual_diff_size_is_not_claimed_as_cloud_savings():
    measured = measure_savings({
        "original_diff_tokens": 52_000_000,
        "local_diff_tokens": 8_000,
        "truncated": True,
    })

    assert measured["gross_cloud_tokens_avoided_est"] == 0
    assert measured["gross_input_tokens_avoided_est"] == 0


def test_deterministic_outline_size_is_diagnostic_only():
    measured = measure_savings({
        "raw_tokens": 40_000,
        "outline_tokens": 800,
        "token_savings_pct": 98.0,
    })

    assert measured["gross_cloud_tokens_avoided_est"] == 0
    assert measured["gross_input_tokens_avoided_est"] == 0


def test_local_context_size_is_not_implicitly_a_cloud_baseline():
    measured = measure_savings({
        "context": "x" * 20000,
        "estimated_tokens": 5000,
        "_avoided_cloud_tokens": 5000,
    })

    assert measured["gross_cloud_tokens_avoided_est"] == 0



def test_agent_supplied_text_does_not_create_fake_positive_savings():
    # If the source text itself is present in tool arguments, request-token cost
    # cancels the apparent routing baseline instead of claiming the input was free.
    text = "z" * 4000
    measured = measure_savings({"input_tokens_est": 1177, "estimated_tokens": 120})
    event = finalize_tool_accounting(
        tool_name="local_ai_task", arguments={"action": "route", "context": text},
        response={"context": "z" * 400}, measured=measured,
    )
    assert event["agent_tool_request_tokens_est"] >= 1177
    assert event["net_cloud_token_delta_est"] <= 0


def test_compact_result_does_not_mutate_original_nested_context():
    from local_ai_hub.compact import compact_result

    original = {
        "text": "x" * 5000,
        "repo_context": {"evidence": [{"path": f"f{i}.py", "raw": "r" * 100} for i in range(20)]},
        "results": [{"text": "z" * 3000, "path": "a.py"}],
    }
    result = compact_result(original, max_text_chars=500, max_evidence=3)
    assert len(original["text"]) == 5000
    assert len(original["repo_context"]["evidence"]) == 20
    assert len(original["results"][0]["text"]) == 3000
    assert len(result["repo_context"]["evidence"]) == 3
    assert result["repo_context"]["evidence_omitted"] == 17
    assert len(result["text"]) < len(original["text"])


def test_compact_result_compacts_nested_output_payloads():
    from local_ai_hub.compact import compact_result

    result = compact_result(
        {"structured": {"text": "x" * 5000, "summary": "y" * 5000, "stdout": "z" * 5000}},
        max_text_chars=500,
    )

    nested = result["structured"]
    assert len(nested["text"]) < 5000
    assert len(nested["summary"]) < 5000
    assert len(nested["stdout"]) < 5000


def test_bounded_repository_search_reports_local_candidate_baseline(tmp_path: Path):
    from local_ai_hub.repo_tools import RepositoryTools

    # RepoTools only needs a small config for deterministic lexical search.
    (tmp_path / "a.py").write_text("\n".join([f"def cache_item_{i}(): return 'cache'" for i in range(30)]), encoding="utf-8")
    cfg = {
        "rag": {"extensions": [".py"], "ignore_dirs": [], "max_file_bytes": 1_000_000},
        "search": {"max_files": 100, "max_hits": 80, "snippet_lines": 1, "max_snippets_per_file": 8, "prefer_git_files": False, "use_ripgrep_if_available": False, "use_git_grep_fallback": False},
    }
    tools = RepositoryTools(cfg)
    try:
        result = tools.search(str(tmp_path), "cache", top_k=2)
        assert result["success"] is True
        assert "token_saving" not in result
        assert result.get("candidate_context_tokens_est", 0) > 0
        measured = measure_savings(result)
        assert measured["gross_input_tokens_avoided_est"] == 0
    finally:
        pass
