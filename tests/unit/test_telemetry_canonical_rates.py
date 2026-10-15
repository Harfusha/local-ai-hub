import math
from contextlib import closing

import pytest

from local_ai_hub.telemetry import TelemetryStore


@pytest.fixture
def telemetry_store(tmp_path):
    store = TelemetryStore(
        tmp_path,
        enabled=True,
        cloud_input_token_cost_usd_per_million=2.0,
        cloud_output_token_cost_usd_per_million=8.0,
    )
    yield store
    store.close()


def test_canonical_rates_default_independently_and_keep_zero(tmp_path):
    defaulted = TelemetryStore(tmp_path / "defaulted")
    zero = TelemetryStore(
        tmp_path / "zero",
        cloud_input_token_cost_usd_per_million=0,
        cloud_output_token_cost_usd_per_million=0.0,
    )
    try:
        assert defaulted.cloud_input_token_cost_usd_per_million == 3.0
        assert defaulted.cloud_output_token_cost_usd_per_million == 3.0
        assert zero.cloud_input_token_cost_usd_per_million == 0.0
        assert zero.cloud_output_token_cost_usd_per_million == 0.0
    finally:
        defaulted.close()
        zero.close()


@pytest.mark.parametrize(
    "rate",
    [True, False, "3.0", None, math.nan, math.inf, -math.inf, -0.01, 10**1000],
)
@pytest.mark.parametrize(
    "field",
    ["cloud_input_token_cost_usd_per_million", "cloud_output_token_cost_usd_per_million"],
)
def test_canonical_rates_reject_invalid_values(tmp_path, field, rate):
    with pytest.raises((TypeError, ValueError)):
        TelemetryStore(tmp_path, **{field: rate})


def test_legacy_rows_keep_signed_accounting_and_report_cost_unknown(telemetry_store):
    telemetry_store.record_tool_accounting(
        {
            "gross_cloud_tokens_avoided_est": 100,
            "net_cloud_token_delta_est": -17,
            "cloud_token_overhead_est": 12,
            "agent_protocol_tokens_est": 5,
            "tool_schema_tokens_est": 7,
            "local_compute_tokens_avoided_est": 11,
        }
    )
    assert telemetry_store.flush()

    summary = telemetry_store.report(scope="process")["summary"]

    assert summary["tool_accounting_events"] == 1
    assert summary["gross_cloud_tokens_avoided_est"] == 100
    assert summary["net_cloud_token_delta_est"] == -17
    assert summary["cloud_token_overhead_est"] == 12
    assert summary["agent_protocol_tokens_est"] == 5
    assert summary["tool_schema_tokens_exposure_est"] == 7
    assert summary["local_compute_tokens_avoided_est"] == 11
    assert summary["estimated_savings_usd"] is None
    assert summary["estimated_input_savings_usd"] is None
    assert summary["estimated_output_savings_usd"] is None
    assert summary["estimated_savings_pricing_mode"] == "incomplete"
    assert "cloud_token_cost_usd_per_million" not in summary


def test_channel_estimates_remain_separate_with_canonical_rates(telemetry_store):
    telemetry_store.record_tool_accounting(
        {
            "gross_cloud_tokens_avoided_est": 150,
            "gross_input_tokens_avoided_est": 100,
            "gross_output_tokens_avoided_est": 50,
            "agent_tool_request_tokens_est": 10,
            "agent_tool_response_tokens_est": 20,
            "net_cloud_token_delta_est": 120,
        }
    )
    assert telemetry_store.flush()

    summary = telemetry_store.report(scope="process")["summary"]

    assert summary["estimated_input_savings_usd"] == round((100 - 20) * 2.0 / 1_000_000, 4)
    assert summary["estimated_output_savings_usd"] == round((50 - 10) * 8.0 / 1_000_000, 4)
    assert summary["estimated_savings_usd"] == 0.0005
    assert summary["estimated_savings_pricing_mode"] == "input_output"


def test_mixed_overlap_and_additive_rows_keep_each_rows_priced_channels(telemetry_store):
    telemetry_store.record_tool_accounting(
        {
            "gross_cloud_tokens_avoided_est": 150_000,
            "gross_input_tokens_avoided_est": 100_000,
            "gross_output_tokens_avoided_est": 100_000,
            "net_cloud_token_delta_est": 150_000,
        }
    )
    telemetry_store.record_tool_accounting(
        {
            "gross_cloud_tokens_avoided_est": 50_000,
            "gross_output_tokens_avoided_est": 50_000,
            "net_cloud_token_delta_est": 50_000,
        }
    )
    assert telemetry_store.flush()

    summary = telemetry_store.report(scope="process")["summary"]

    assert summary["gross_cloud_tokens_avoided_est"] == 200_000
    assert summary["gross_input_cloud_tokens_avoided_est"] + summary["gross_output_cloud_tokens_avoided_est"] == 250_000
    assert summary["estimated_input_savings_usd"] == 0.2
    assert summary["estimated_output_savings_usd"] == 0.4
    assert summary["estimated_savings_usd"] == 0.6
    assert summary["estimated_savings_pricing_mode"] == "input_output"


def test_missing_row_coverage_stays_unknown_when_overlapping_channels_cancel_gap(telemetry_store):
    telemetry_store.record_tool_accounting(
        {"gross_cloud_tokens_avoided_est": 100, "net_cloud_token_delta_est": 100}
    )
    telemetry_store.record_tool_accounting(
        {
            "gross_cloud_tokens_avoided_est": 100,
            "gross_input_tokens_avoided_est": 100,
            "gross_output_tokens_avoided_est": 100,
            "net_cloud_token_delta_est": 100,
        }
    )
    assert telemetry_store.flush()

    summary = telemetry_store.report(scope="process")["summary"]

    assert summary["gross_cloud_tokens_avoided_est"] == 200
    assert summary["gross_input_cloud_tokens_avoided_est"] + summary["gross_output_cloud_tokens_avoided_est"] == 200
    assert summary["estimated_input_savings_usd"] == 0.0002
    assert summary["estimated_savings_usd"] is None
    assert summary["estimated_savings_pricing_mode"] == "incomplete"
    projected = telemetry_store.realtime_summary(scope="process")
    assert projected["estimated_savings_usd"] is None
    assert projected["estimated_savings_pricing_mode"] == "incomplete"


def test_missing_zero_channel_row_stays_unknown_when_signed_deltas_cancel(telemetry_store):
    telemetry_store.record_tool_accounting(
        {"net_cloud_token_delta_est": 10_000}
    )
    telemetry_store.record_tool_accounting(
        {
            "agent_tool_response_tokens_est": 10_000,
            "net_cloud_token_delta_est": -10_000,
        }
    )
    assert telemetry_store.flush()

    summary = telemetry_store.report(scope="process")["summary"]

    assert summary["net_cloud_token_delta_est"] == 0
    assert summary["estimated_input_savings_usd"] == -0.02
    assert summary["estimated_savings_usd"] is None
    assert summary["estimated_savings_pricing_mode"] == "incomplete"


def test_rollup_without_channel_coverage_marks_window_cost_incomplete(telemetry_store):
    from datetime import datetime, timedelta, timezone

    future_day = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    with closing(telemetry_store._connect()) as con:
        con.execute(
            """INSERT INTO daily_rollups(day,event_type,action,agent,model,cache_layer,success,events,
                       gross_avoided_cloud_tokens)
               VALUES(?,?,?,?,?,?,1,1,100)""",
            (future_day, "tool_accounting", "", "", "", ""),
        )
        con.commit()

    summary = telemetry_store.report(scope="window")["summary"]

    assert summary["gross_cloud_tokens_avoided_est"] == 100
    assert summary["estimated_savings_usd"] is None
    assert summary["estimated_savings_pricing_mode"] == "incomplete"
