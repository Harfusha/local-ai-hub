from contextlib import closing

from local_ai_hub.telemetry import TelemetryStore


def test_decision_grade_queue_uses_created_index_and_preserves_id_order(tmp_path):
    store = TelemetryStore(tmp_path, enabled=False)
    store._init_db()
    cutoff = 1_000.0

    # IDs 1-1002 have deliberately descending timestamps. The cutoff-equal
    # event is the newest by ID, while IDs 1 and 2 have newer timestamps.
    events = [
        (event_id, cutoff + (1002 - event_id), float(event_id))
        for event_id in range(1, 1003)
    ]
    events.extend(
        [
            (1003, cutoff - 1, 1003.0),  # outside the inclusive time window
            (1004, cutoff, 0.0),  # cutoff-equal but not a positive queue age
            (1005, cutoff + 10, -5.0),  # negative queue age
        ]
    )

    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO events(id, created_at, queue_age_ms) VALUES(?, ?, ?)",
            events,
        )
        statements = []
        con.set_trace_callback(statements.append)
        summary = store._decision_grade(con, cutoff)

        queue_sql = next(
            statement
            for statement in statements
            if "queue_age_ms FROM events" in statement
        )
        plan = con.execute(f"EXPLAIN QUERY PLAN {queue_sql}").fetchall()

    assert summary["queue"]["events"] == 1000
    assert summary["queue"]["avg_age_ms"] == 502.5
    assert summary["queue"]["max_age_ms"] == 1002.0
    details = [str(row[3]) for row in plan]
    assert any("USING INDEX idx_events_created" in detail for detail in details)
    assert not any("SCAN events" in detail for detail in details)
