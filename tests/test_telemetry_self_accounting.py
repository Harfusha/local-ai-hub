from local_ai_hub.telemetry import TelemetryStore


def test_telemetry_instrumentation_is_not_recorded_as_user_tool_workload():
    store = object.__new__(TelemetryStore)
    recorded = []
    store.record = lambda **event: recorded.append(event)

    store.record_tool_accounting(
        {
            "tool": "local_ai_telemetry",
            "agent_tool_request_tokens_est": 120,
            "agent_tool_response_tokens_est": 240,
            "gross_cloud_tokens_avoided_est": 80,
        }
    )
    store.record_tool_accounting(
        {
            "tool": "get_telemetry",
            "agent_tool_request_tokens_est": 12,
            "agent_tool_response_tokens_est": 24,
        }
    )

    assert len(recorded) == 1
    assert recorded[0]["action"] == "get_telemetry"
    assert recorded[0]["tool_calls"] == 1
