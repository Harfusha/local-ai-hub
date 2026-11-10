from __future__ import annotations

import json
import sqlite3

from local_ai_hub import diagnostics_export


def test_support_snapshot_removes_candidate_text_hashes_and_capture_traces(tmp_path):
    db_path = tmp_path / "agent_state.sqlite"
    candidate_text = "PRIVATE_LAYA_STATE_b99e3d"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE laya_candidates (candidate_id TEXT, content_hash TEXT, candidate_json TEXT);
        CREATE TABLE laya_candidate_events (metadata_json TEXT);
        CREATE TABLE laya_dataset_snapshots (manifest_json TEXT);
        CREATE TABLE laya_dataset_assignments (content_hash TEXT);
        CREATE TABLE traces (
            trace_id TEXT PRIMARY KEY, request_json TEXT, effective_payload_json TEXT,
            output_text TEXT, response_json TEXT
        );
        CREATE TABLE trace_events (trace_id TEXT, seq INTEGER, payload_json TEXT);
        CREATE TABLE trace_content_meta (trace_id TEXT, content_field TEXT);
        CREATE TABLE trace_content_chunks (trace_id TEXT, content_field TEXT, chunk_text TEXT);
        """
    )
    connection.execute(
        "INSERT INTO laya_candidates VALUES ('candidate-1','sensitive-hash',?)",
        (json.dumps({"state": candidate_text}),),
    )
    connection.execute("INSERT INTO laya_candidate_events VALUES (?)", (json.dumps({"task_id": "task-1"}),))
    capture = json.dumps({"laya_operation": {"action": "capture_batch", "examples": [{"candidate": {"state": candidate_text}}]}})
    connection.execute("INSERT INTO traces VALUES ('trace-candidate',?,'','','')", (capture,))
    connection.execute("INSERT INTO traces VALUES ('trace-unrelated','{}','','','')")
    connection.execute("INSERT INTO trace_events VALUES ('trace-candidate',1,?)", (capture,))
    connection.execute("INSERT INTO trace_content_meta VALUES ('trace-candidate','request')")
    connection.execute("INSERT INTO trace_content_chunks VALUES ('trace-candidate','request',?)", (candidate_text,))
    connection.commit()
    connection.close()

    removed = diagnostics_export._sanitize_laya_snapshot(
        db_path, redact_candidates=True, redact_traces=True
    )

    assert removed == {"candidate_rows": 1, "candidate_tables": 4, "trace_records": 1}
    assert candidate_text.encode() not in db_path.read_bytes()
    assert b"sensitive-hash" not in db_path.read_bytes()
    sanitized = sqlite3.connect(db_path)
    try:
        assert sanitized.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='laya_candidates'"
        ).fetchone() is None
        assert sanitized.execute("SELECT trace_id FROM traces").fetchall() == [("trace-unrelated",)]
        assert sanitized.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0] == 0
        assert sanitized.execute("SELECT COUNT(*) FROM trace_content_chunks").fetchone()[0] == 0
    finally:
        sanitized.close()


def test_support_snapshot_sanitizer_is_noop_when_laya_tables_are_absent(tmp_path):
    db_path = tmp_path / "telemetry.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE events (event_type TEXT, payload TEXT)")
    connection.execute("INSERT INTO events VALUES ('request','keep')")
    connection.commit()
    connection.close()

    removed = diagnostics_export._sanitize_laya_snapshot(
        db_path, redact_candidates=True, redact_traces=True
    )

    assert removed == {"candidate_rows": 0, "candidate_tables": 0, "trace_records": 0}
    sanitized = sqlite3.connect(db_path)
    try:
        assert sanitized.execute("SELECT payload FROM events").fetchall() == [("keep",)]
    finally:
        sanitized.close()


def test_partial_capture_batch_trace_is_treated_as_private():
    assert diagnostics_export._contains_laya_capture(
        '{"laya_operation":{"action":"capture_batch","examples":['
    )
