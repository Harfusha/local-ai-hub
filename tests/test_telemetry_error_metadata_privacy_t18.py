from __future__ import annotations

from local_ai_hub.telemetry import TelemetryStore


def test_error_metadata_is_redacted_in_both_persisted_tables(tmp_path):
    private_values = [
        "PROMPT-PRIVATE-ONE",
        "PROMPT-PRIVATE-TWO",
        "SOURCE-PRIVATE-ONE",
        "SOURCE-PRIVATE-TWO",
        "SECRET-PRIVATE-ONE",
        "SECRET-PRIVATE-TWO",
        r"C:\private\project\one.py",
        r"C:\private\project\two.py",
        "/private/project/one.py",
        "/private/project/two.py",
        "/api/projects/private-one",
        "/api/projects/private-two",
        r"\\server\share\project\one.py",
        r"\\server\share\project\two.py",
        "/secret-one.txt",
        "/secret-two.txt",
    ]
    cases = [
        {
            "prompt": private_values[0],
            "source": private_values[2],
            "secret": private_values[4],
            "windows": private_values[6],
            "posix": private_values[8],
            "api": private_values[10],
            "unc": private_values[12],
            "root": private_values[14],
        },
        {
            "prompt": private_values[1],
            "source": private_values[3],
            "secret": private_values[5],
            "windows": private_values[7],
            "posix": private_values[9],
            "api": private_values[11],
            "unc": private_values[13],
            "root": private_values[15],
        },
    ]
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index, (case, status_code) in enumerate(
            [(cases[0], 503), (cases[1], 503), (cases[0], 504)],
            start=1,
        ):
            error = RuntimeError(
                f'"prompt":"{case["prompt"]}" "source_text":"{case["source"]}" '
                f'"api_key":"{case["secret"]}"'
            )
            error.status_code = status_code
            store.record_error(
                f'provider file={case["windows"]} unc={case["unc"]} route={case["api"]} '
                f'"prompt":"{case["prompt"]}"',
                f'generate file={case["posix"]} root={case["root"]} route={case["api"]} '
                f'"source_text":"{case["source"]}"',
                error,
                request_id=f'req-{index} token="{case["secret"]}"',
                tenant=f'tenant-{index} password="{case["secret"]}"',
                agent=f'worker-{index} source="{case["source"]}"',
                retryable=True,
                recovered=True,
            )
        assert store.flush(1)
        con = store._connect()
        try:
            errors = con.execute(
                "SELECT component, operation, error_type, safe_message, fingerprint, "
                "request_id, tenant, agent, retryable, recovered FROM errors ORDER BY rowid"
            ).fetchall()
            events = con.execute(
                "SELECT action, error_type, error_fingerprint, request_id, tenant, agent "
                "FROM events WHERE event_type='error' ORDER BY rowid"
            ).fetchall()
        finally:
            con.close()
    finally:
        store.close()

    assert len(errors) == len(events) == 3
    for row in [*errors, *events]:
        persisted = repr(row)
        assert all(value not in persisted for value in private_values)
    assert errors[0][0].startswith("provider")
    assert errors[0][1].startswith("generate")
    assert all(row[2:4] == ("RuntimeError", "RuntimeError: operation failed") for row in errors)
    assert all(row[8:] == (1, 1) for row in errors)
    assert errors[0][4] == errors[1][4]
    assert errors[0][4] != errors[2][4]
    assert all("provider" in row[0] and "generate" in row[0] for row in events)
    assert all(row[1] == "RuntimeError" for row in events)
    assert events[0][2] == events[1][2]
    assert events[0][2] != events[2][2]
    for row in [*errors, *events]:
        persisted = repr(row)
        assert all(value not in persisted for value in private_values)


def test_root_level_posix_paths_are_redacted_from_persisted_error_fields(tmp_path):
    paths = ("/secret", "/home/alice", "/etc/passwd", "/x")
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index, path in enumerate(paths):
            store.record_error(
                f"path={path}",
                "generate",
                RuntimeError("failure"),
                request_id=f"request-{index}",
            )
        assert store.flush(1)
        con = store._connect()
        try:
            errors = con.execute("SELECT component, operation FROM errors ORDER BY rowid").fetchall()
            events = con.execute(
                "SELECT action FROM events WHERE event_type='error' ORDER BY rowid"
            ).fetchall()
        finally:
            con.close()
    finally:
        store.close()

    assert len(errors) == len(events) == len(paths)
    assert all(row == ("path=<path>", "generate") for row in errors)
    assert all(row == ("path=<path>:generate",) for row in events)
    for path, error_row, event_row in zip(paths, errors, events):
        assert path not in repr(error_row)
        assert path not in repr(event_row)


def test_http_pathlike_labels_are_redacted_but_benign_routes_survive(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_http(action="/secret", route="/x", success=True, duration_ms=1)
        store.record_http(action="/slow", route="/median", success=True, duration_ms=2)
        store.record_http(
            action="/api/users/alice",
            route="/api/projects/private-name",
            success=True,
            duration_ms=3,
        )
        assert store.flush(1)
        con = store._connect()
        try:
            rows = con.execute(
                "SELECT action, route FROM events WHERE event_type='http' ORDER BY rowid"
            ).fetchall()
        finally:
            con.close()
    finally:
        store.close()

    assert rows == [
        ("<path>", "<path>"),
        ("/slow", "/median"),
        ("<path>", "<path>"),
    ]
    assert "/secret" not in repr(rows)
    assert "/x" not in repr(rows)
    assert "/api/users/alice" not in repr(rows)
    assert "/api/projects/private-name" not in repr(rows)
