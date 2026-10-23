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


def test_http_error_operations_preserve_registered_endpoints_and_distinct_fingerprints(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        search_fp = store.record_error("http", "/api/search?token=private#fragment", ValueError("private"))
        command_fp = store.record_error("http", "/api/agent-state/tasks", ValueError("private"))
        store.record_error("http", "/home/adam/private/project.db", ValueError("private"))
        store.record_error("http", "/api/projects/private-name", ValueError("private"))
        assert store.flush(5)
        connection = store._connect()
        try:
            operations = connection.execute("SELECT operation FROM errors ORDER BY rowid").fetchall()
            actions = connection.execute("SELECT action FROM events WHERE event_type='error' ORDER BY rowid").fetchall()
        finally:
            connection.close()
        assert operations == [("/api/search",), ("/api/agent-state/tasks",), ("<path>",), ("<path>",)]
        assert search_fp != command_fp
        assert actions[:2] == [("/api/search",), ("/api/agent-state/tasks",)]
    finally:
        store.close()
