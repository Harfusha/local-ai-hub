from local_ai_hub.telemetry import TelemetryStore


def test_clean_event_preserves_registered_routes_for_action_labels_across_event_types():
    for event_type in ("request_start", "terminal_client_result"):
        event = TelemetryStore._clean_event(
            {
                "event_type": event_type,
                "action": "/api/context/pack?token=private",
            }
        )
        assert event["action"] == "/api/context/pack"

    dynamic = TelemetryStore._clean_event(
        {
            "event_type": "terminal_client_result",
            "action": "/api/debug-traces/trace-secret?token=private",
        }
    )
    assert dynamic["action"] == "/api/debug-traces/{trace_id}"
    assert "trace-secret" not in dynamic["action"]
    assert "private" not in dynamic["action"]


def test_clean_event_preserves_all_registered_post_routes_without_query_strings():
    from local_ai_hub.http_route_registry import POST_ROUTE_REGISTRY

    for rule in POST_ROUTE_REGISTRY:
        for path in rule.paths:
            event = TelemetryStore._clean_event(
                {
                    "event_type": "request_start",
                    "action": f"{path}?token=private",
                }
            )

            assert event["action"] == path
            assert "private" not in event["action"]


def test_clean_event_still_redacts_filesystem_paths_from_action_labels():
    event = TelemetryStore._clean_event(
        {
            "event_type": "terminal_client_result",
            "action": "/home/adam/private/project.db",
        }
    )

    assert event["action"] == "<path>"
