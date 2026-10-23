from contextlib import closing

from local_ai_hub.telemetry import TelemetryStore


def _decision_grade(tmp_path, cutoff, events=()):
    store = TelemetryStore(tmp_path, enabled=False)
    store._init_db()
    statements = []
    with closing(store._connect()) as con:
        con.executemany(
            """INSERT INTO events(
                   created_at, terminal, retryable, receipt_count, cache_hit,
                   coalesced, bypass_reason, success
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            events,
        )
        con.set_trace_callback(statements.append)
        summary = store._decision_grade(con, cutoff)
    return summary, statements


def test_decision_grade_combines_scalar_metrics_without_changing_values(tmp_path):
    cutoff = 1_000.0
    events = [
        (cutoff, 1, 0, 2, 1, 0, "rate", 0),
        (cutoff + 1, 0, 1, 0, 0, 1, "", 1),
        (cutoff + 2, -1, -1, -3, 1, 0, "policy", 0),
        (cutoff + 3, 1, -1, 2, 0, 1, "", 1),
        (cutoff - 1, 1, 1, 100, 1, 1, "old", 0),
    ]

    summary, statements = _decision_grade(tmp_path, cutoff, events)

    assert summary["counts"] == {
        "events": 4,
        "cache_hits": 2,
        "bypasses": 2,
        "terminal": 2,
        "retryable": 1,
        "receipts": 1,
        "cache_hit_count": 2,
        "bypass_count": 2,
        "terminal_count": 2,
        "retryable_count": 1,
        "receipt_count": 1,
    }
    assert summary["outcomes"] == {
        "terminal": 2,
        "retryable": 1,
        "terminal_known": 3,
        "retryable_known": 2,
    }
    assert summary["receipts"] == {"events": 2, "total": 1, "max_per_event": 2}
    assert summary["errors"] == {"failures": 2}
    assert summary["cache"] == [
        {"layer": "uncategorized", "events": 4, "hits": 2, "coalesced": 2, "hit_rate": 0.5}
    ]
    assert summary["bypass"] == [
        {"reason": "policy", "events": 1},
        {"reason": "rate", "events": 1},
    ]
    assert len(
        [
            statement
            for statement in statements
            if "FROM events WHERE created_at>=" in statement
            and "receipt_count" in statement
            and "terminal" in statement
            and "success" in statement
        ]
    ) == 1


def test_decision_grade_empty_database_returns_zero_aggregates(tmp_path):
    summary, statements = _decision_grade(tmp_path, cutoff=1_000.0)

    assert summary["counts"] == {
        "events": 0,
        "cache_hits": 0,
        "bypasses": 0,
        "terminal": 0,
        "retryable": 0,
        "receipts": 0,
        "cache_hit_count": 0,
        "bypass_count": 0,
        "terminal_count": 0,
        "retryable_count": 0,
        "receipt_count": 0,
    }
    assert summary["outcomes"] == {
        "terminal": 0,
        "retryable": 0,
        "terminal_known": 0,
        "retryable_known": 0,
    }
    assert summary["receipts"] == {"events": 0, "total": 0, "max_per_event": 0}
    assert summary["errors"] == {"failures": 0}
    assert summary["routes"] == []
    assert summary["cache"] == []
    assert summary["bypass"] == []
    assert summary["_truncated"] is False
    assert len(
        [
            statement
            for statement in statements
            if "FROM events WHERE created_at>=" in statement
            and "receipt_count" in statement
            and "terminal" in statement
            and "success" in statement
        ]
    ) == 1
