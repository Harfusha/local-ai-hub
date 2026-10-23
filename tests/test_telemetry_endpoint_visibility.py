from contextlib import closing

from local_ai_hub.telemetry import TelemetryStore


def test_request_start_live_projection_preserves_registered_endpoint_labels(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index, path in enumerate(("/api/search", "/api/agent-state/tasks"), start=1):
            store.record_live(
                kind="request",
                event_type="request_start",
                request_id=f"request-{index}",
                action=f"{path}?query=private#fragment",
            )

        active = store.realtime_summary()["active_requests"]
        assert {request["action"] for request in active} == {
            "/api/search",
            "/api/agent-state/tasks",
        }
        assert all("private" not in request["action"] for request in active)
        assert all("fragment" not in request["action"] for request in active)
    finally:
        store.close()


def test_persisted_http_views_preserve_registered_routes_and_hide_unknown_paths(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index, path in enumerate(("/api/search", "/api/agent-state/tasks"), start=1):
            store.record_http(
                request_id=f"http-{index}",
                action=f"{path}?query=private#fragment",
                status_code=200,
                success=True,
            )
        store.record_http(action="/home/adam/private/project.db", status_code=200)
        store.record_http(action="/api/projects/private", status_code=200)
        assert store.flush(5)

        recent = store.recent_http()
        timeline = store.get_timeline()
        for rows in (recent, timeline):
            actions = {row["action"] for row in rows}
            assert {"/api/search", "/api/agent-state/tasks"} <= actions
            assert "<path>" in actions
            assert "/api/projects/private" not in actions
            assert all("query=private" not in action for action in actions)
            assert all("#fragment" not in action for action in actions)
    finally:
        store.close()


def test_error_report_preserves_registered_and_trace_template_routes_only(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_error("http", "/api/search?query=private#fragment", ValueError("failure"))
        store.record_error("http", "/api/agent-state/tasks?query=private#fragment", ValueError("failure"))
        store.record_error(
            "http", "/api/debug-traces/trace-secret?query=private#fragment", ValueError("failure")
        )
        store.record_error("http", "/home/adam/private/project.db", ValueError("failure"))
        store.record_error("http", "/api/projects/private", ValueError("failure"))
        assert store.flush(5)

        report = store.report(recent_errors=20)
        operations = {error["operation"] for error in report["error_fingerprints"]}
        assert {"/api/search", "/api/agent-state/tasks", "/api/debug-traces/{trace_id}"} <= operations
        assert "<path>" in operations
        assert "/api/projects/private" not in operations
        assert "trace-secret" not in str(report["error_fingerprints"])
        assert "query=private" not in str(report["error_fingerprints"])

        with closing(store._connect()) as connection:
            stored_operations = {
                row[0] for row in connection.execute("SELECT operation FROM errors")
            }
        assert operations == stored_operations
    finally:
        store.close()
