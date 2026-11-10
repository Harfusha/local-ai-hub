from __future__ import annotations

import json
import os
import sqlite3

import pyzipper
import pytest

from local_ai_hub.diagnostics_export import _sanitize_laya_snapshot, create_diagnostics_archive


def _database(path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE diagnostics (project_root TEXT, payload TEXT)")
        connection.executemany("INSERT INTO diagnostics VALUES (?, ?)", rows)
        connection.commit()
    finally:
        connection.close()


def _source_tree(root):
    (root / "src" / "local_ai_hub").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "src" / "local_ai_hub" / "app.py").write_text("hub source", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("hub test", encoding="utf-8")
    (root / "docs" / "INSTALL_PROMPT.md").write_text("hub prompt", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='local-ai-hub'", encoding="utf-8")
    (root / "other-project").mkdir()
    (root / "other-project" / "private.py").write_text("other project", encoding="utf-8")
    (root / "models").mkdir()
    (root / "models" / "weights.gguf").write_bytes(b"model weights")
    (root / ".env").write_text("API_TOKEN=do-not-copy", encoding="utf-8")


def test_diagnostics_snapshot_removes_new_laya_candidate_receipt_tables(tmp_path):
    database = tmp_path / "agent_state.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE laya_candidate_consent_receipts (candidate_id TEXT, receipt_id TEXT)"
    )
    connection.execute(
        "INSERT INTO laya_candidate_consent_receipts VALUES ('candidate-1', 'private-receipt')"
    )
    connection.commit()
    connection.close()

    result = _sanitize_laya_snapshot(database, redact_candidates=True, redact_traces=False)

    assert result["candidate_tables"] == 1
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='laya_candidate_consent_receipts'"
        ).fetchone() is None
    finally:
        connection.close()


def test_support_archive_streams_global_state_source_and_redacted_config(tmp_path):
    state_dir = tmp_path / "state"
    _database(state_dir / "telemetry.sqlite3", [("project-a", "event-a"), ("project-b", "event-b")])
    _database(state_dir / "agent_state.sqlite3", [("project-a", "task and memory state")])
    _database(state_dir / "projects" / "project-b" / "rag.sqlite3", [("project-b", "retrieval state")])
    (state_dir / "logs" / "service").mkdir(parents=True)
    (state_dir / "logs" / "service" / "hub.log").write_text("hub diagnostic", encoding="utf-8")
    (state_dir / "logs" / "service" / "hub.log.1").write_text("rotated diagnostic", encoding="utf-8")
    source_root = tmp_path / "hub"
    _source_tree(source_root)

    with create_diagnostics_archive(
        state_dir,
        config={"server": {"bind": "127.0.0.1", "api_key": "secret-value"}, "models": {"default": "qwen"}},
        source_root=source_root,
        temp_dir=tmp_path,
    ) as export:
        assert export.path.is_file()
        assert export.size == export.path.stat().st_size
        assert export.size > 0
        with pyzipper.AESZipFile(export.path) as archive:
            archive.setpassword(export.password.encode("ascii"))
            names = set(archive.namelist())
            assert {
                "state/telemetry.sqlite3",
                "state/agent_state.sqlite3",
                "state/projects/project-b/rag.sqlite3",
                "state/logs/service/hub.log",
                "state/logs/service/hub.log.1",
                "hub/src/local_ai_hub/app.py",
                "hub/tests/test_app.py",
                "hub/docs/INSTALL_PROMPT.md",
                "hub/pyproject.toml",
                "config/effective_config.redacted.json",
                "manifest.json",
                "README.txt",
            } <= names
            assert "hub/other-project/private.py" not in names
            assert "hub/models/weights.gguf" not in names
            assert "hub/.env" not in names
            assert archive.getinfo("state/telemetry.sqlite3").wz_aes_strength == 3
            assert archive.getinfo("state/telemetry.sqlite3").compress_type == pyzipper.ZIP_BZIP2
            config = json.loads(archive.read("config/effective_config.redacted.json"))
            assert config["server"]["api_key"] == "[REDACTED]"
            assert archive.getinfo("state/telemetry.sqlite3").extract_version >= 45
            config = json.loads(archive.read("config/effective_config.redacted.json"))
            assert config["server"]["bind"] == "127.0.0.1"
            assert config["server"]["api_key"] == "[REDACTED]"
            assert config["models"]["default"] == "qwen"
            exported_manifest = json.loads(archive.read("manifest.json"))
            assert exported_manifest["scope"] == "installation_all_projects"
            assert exported_manifest["redacted_config"] is True
            assert exported_manifest["source_files"] >= 4
            assert exported_manifest["excluded_categories"] == ["environment secrets", "model weights", "other project source"]
            db = sqlite3.connect(":memory:")
            db.deserialize(archive.read("state/telemetry.sqlite3"))
            assert db.execute("SELECT project_root, payload FROM diagnostics ORDER BY project_root").fetchall() == [
                ("project-a", "event-a"),
                ("project-b", "event-b"),
            ]
            db.close()
        archive_path = export.path
        assert len(export.password) >= 40

    assert not archive_path.exists()


def test_support_archive_exports_laya_shadow_metadata_and_manifest(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    laya_telemetry = {
        "generated_at": 1_700_000_000.0,
        "window_days": 7,
        "decisions": {
            "available": True,
            "mode_counts": {"shadow": 3},
            "category_counts": {"context_source": 3},
            "status_counts": {"success": 2, "abstain": 1},
        },
        "runtime": {"status": "NOT_VERIFIED"},
    }

    with create_diagnostics_archive(
        state_dir,
        laya_telemetry=laya_telemetry,
        source_root=tmp_path / "no-source",
        temp_dir=tmp_path,
    ) as export:
        with pyzipper.AESZipFile(export.path) as archive:
            archive.setpassword(export.password.encode("ascii"))
            names = set(archive.namelist())
            assert "laya/report.json" in names
            assert "laya/candidates.train.jsonl" not in names
            report = json.loads(archive.read("laya/report.json"))
            manifest = json.loads(archive.read("manifest.json"))

    assert report["schema_version"] == 1
    assert report["period"] == {
        "scope": "window",
        "generated_at": laya_telemetry["generated_at"],
        "window_days": 7,
    }
    assert report["shadow_telemetry"] == laya_telemetry
    assert report["runtime"] == {"status": "NOT_VERIFIED"}
    assert report["missing_data"]["shadow_telemetry"] == 0
    assert report["missing_data"]["evaluation_report"] == 1
    assert report["candidate_text_export"]["status"] == "omitted"
    assert report["candidate_text_export"]["included_rows"] == 0
    assert manifest["laya"]["candidate_text"]["status"] == "omitted"
    assert manifest["laya"]["missing_data"] == report["missing_data"]
    assert any(
        item["name"] == "laya/report.json"
        and item["category"] == "laya_metadata_report"
        and item["status"] == "included"
        for item in manifest["files"]
    )


def test_support_archive_uses_fresh_password_and_enforces_configured_limits(tmp_path):
    state_dir = tmp_path / "state"
    (state_dir / "logs").mkdir(parents=True)
    (state_dir / "logs" / "hub.log").write_bytes(os.urandom(8192))

    no_source = tmp_path / "no-source"
    with create_diagnostics_archive(state_dir, source_root=no_source, temp_dir=tmp_path) as first:
        first_password = first.password
    with create_diagnostics_archive(state_dir, source_root=no_source, temp_dir=tmp_path) as second:
        assert second.password != first_password

    with pytest.raises(ValueError, match="source data exceeds configured source limit"):
        create_diagnostics_archive(state_dir, source_root=no_source, max_source_bytes=1024, temp_dir=tmp_path)

    with pytest.raises(ValueError, match="archive exceeds configured limit"):
        create_diagnostics_archive(state_dir, source_root=no_source, max_archive_bytes=1024, temp_dir=tmp_path)


def test_support_archive_cancellation_removes_temporary_files(tmp_path):
    state_dir = tmp_path / "state"
    (state_dir / "logs").mkdir(parents=True)
    (state_dir / "logs" / "hub.log").write_bytes(b"diagnostic" * 2048)

    with pytest.raises(RuntimeError, match="export cancelled"):
        create_diagnostics_archive(
            state_dir,
            source_root=tmp_path / "no-source",
            temp_dir=tmp_path,
            cancelled=lambda: True,
        )

    assert list(tmp_path.glob("local-ai-hub-export-*")) == []


def test_support_archive_redacts_laya_candidates_from_database_and_debug_traces(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    sentinel = "PRIVATE_LAYA_CANDIDATE_TEXT_7f9263"
    receipt_sentinel = "PRIVATE_LAYA_CONSENT_RECEIPT_53ab"

    agent_state = sqlite3.connect(state_dir / "agent_state.sqlite")
    agent_state.execute("CREATE TABLE laya_candidates (candidate_id TEXT, candidate_json TEXT, content_hash TEXT)")
    agent_state.execute("INSERT INTO laya_candidates VALUES ('candidate-1', ?, 'private-hash')", (json.dumps({"state": sentinel}),))
    agent_state.execute("CREATE TABLE laya_candidate_events (metadata_json TEXT)")
    agent_state.execute("INSERT INTO laya_candidate_events VALUES ('{}')")
    agent_state.execute("CREATE TABLE laya_candidate_consent_receipts (candidate_id TEXT, receipt_id TEXT)")
    agent_state.execute(
        "INSERT INTO laya_candidate_consent_receipts VALUES ('candidate-1', ?)", (receipt_sentinel,)
    )
    agent_state.commit()
    agent_state.close()

    trace_db = sqlite3.connect(state_dir / "debug_traces.sqlite3")
    trace_db.execute("CREATE TABLE traces (trace_id TEXT PRIMARY KEY, request_json TEXT, effective_payload_json TEXT, output_text TEXT, response_json TEXT)")
    trace_db.execute("CREATE TABLE trace_events (trace_id TEXT, seq INTEGER, created_at REAL, event_type TEXT, payload_json TEXT)")
    trace_db.execute("CREATE TABLE trace_content_meta (trace_id TEXT, content_field TEXT, event_seq INTEGER, encoding TEXT, total_chars INTEGER, total_bytes INTEGER, storage_truncated INTEGER)")
    trace_db.execute("CREATE TABLE trace_content_chunks (trace_id TEXT, content_field TEXT, event_seq INTEGER, chunk_index INTEGER, chunk_text TEXT)")
    request = json.dumps({"laya_operation": {"action": "capture", "candidate": {"state": sentinel}}})
    trace_db.execute("INSERT INTO traces VALUES ('trace-1', ?, '', '', '')", (request,))
    trace_db.execute("INSERT INTO trace_events VALUES ('trace-1', 1, 0, 'request', ?)", (request,))
    trace_db.execute("INSERT INTO trace_content_meta VALUES ('trace-1', 'request', 0, 'json', ?, ?, 0)", (len(request), len(request)))
    trace_db.execute("INSERT INTO trace_content_chunks VALUES ('trace-1', 'request', 0, 0, ?)", (sentinel,))
    event_only_sentinel = "PRIVATE_LAYA_EVENT_ONLY_61c22a"
    event_only = json.dumps({"laya_operation": {"action": "capture", "candidate": {"state": event_only_sentinel}}})
    trace_db.execute("INSERT INTO traces VALUES ('trace-event-only', '', '', '', '')")
    trace_db.execute("INSERT INTO trace_events VALUES ('trace-event-only', 1, 0, 'custom', '')")
    trace_db.execute("INSERT INTO trace_content_meta VALUES ('trace-event-only', 'event', 1, 'json', ?, ?, 0)", (len(event_only), len(event_only)))
    split_at = event_only.index(event_only_sentinel) + 7
    trace_db.execute("INSERT INTO trace_content_chunks VALUES ('trace-event-only', 'event', 1, 0, ?)", (event_only[:split_at],))
    trace_db.execute("INSERT INTO trace_content_chunks VALUES ('trace-event-only', 'event', 1, 1, ?)", (event_only[split_at:],))
    trace_db.commit()
    trace_db.close()

    with create_diagnostics_archive(state_dir, source_root=tmp_path / "no-source", temp_dir=tmp_path) as export:
        with pyzipper.AESZipFile(export.path) as archive:
            archive.setpassword(export.password.encode("ascii"))
            state_copy = archive.read("state/agent_state.sqlite")
            trace_copy = archive.read("state/debug_traces.sqlite3")
            assert sentinel.encode() not in state_copy
            assert receipt_sentinel.encode() not in state_copy
            assert b"private-hash" not in state_copy
            assert sentinel.encode() not in trace_copy
            assert event_only_sentinel.encode() not in trace_copy

            sanitized_state_path = tmp_path / "sanitized-agent-state.sqlite"
            sanitized_state_path.write_bytes(state_copy)
            sanitized_state = sqlite3.connect(sanitized_state_path)
            try:
                assert sanitized_state.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='laya_candidates'"
                ).fetchone() is None
                assert sanitized_state.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='laya_candidate_consent_receipts'"
                ).fetchone() is None
            finally:
                sanitized_state.close()

            sanitized_trace_path = tmp_path / "sanitized-debug-traces.sqlite"
            sanitized_trace_path.write_bytes(trace_copy)
            sanitized_traces = sqlite3.connect(sanitized_trace_path)
            try:
                assert sanitized_traces.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 0
                assert sanitized_traces.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0] == 0
                assert sanitized_traces.execute("SELECT COUNT(*) FROM trace_content_chunks").fetchone()[0] == 0
            finally:
                sanitized_traces.close()


def test_support_archive_writes_laya_metadata_and_only_explicit_candidate_member(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    laya_metadata = {
        "schema_version": "laya-support-v1",
        "telemetry": {"available": True, "records": 4, "counts_by_mode": {"shadow": 3, "advisory": 1}},
        "candidates": {"status_counts": {"verified": 2, "pending": 1}},
        "candidate_text_export": {"status": "included", "reason": None, "included_rows": 99},
    }

    with create_diagnostics_archive(
        state_dir, source_root=tmp_path / "no-source", temp_dir=tmp_path,
        laya_metadata=laya_metadata,
    ) as export:
        with pyzipper.AESZipFile(export.path) as archive:
            archive.setpassword(export.password.encode("ascii"))
            names = set(archive.namelist())
            assert "laya/report.json" in names
            assert "laya/candidates.train.jsonl" not in names
            report = json.loads(archive.read("laya/report.json"))
            assert report["candidate_text_export"] == {
                "status": "omitted",
                "included_rows": 0,
                "skipped_rows": 0,
                "skipped_by_status": {"pending": 0, "rejected": 0, "ambiguous": 0},
                "reason": "explicit_opt_in_required",
            }
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["laya"]["candidate_text"]["status"] == "omitted"
            assert manifest["laya"]["candidate_text"]["included_rows"] == 0

    candidate_payload = b'{"state":"approved minimal state","questions":{},"expected":{}}\n'
    included_metadata = {**laya_metadata, "candidate_text_export": {"status": "omitted", "included_rows": 0}}
    with create_diagnostics_archive(
        state_dir, source_root=tmp_path / "no-source", temp_dir=tmp_path,
        laya_metadata=included_metadata, laya_candidate_payload=candidate_payload,
    ) as export:
        with pyzipper.AESZipFile(export.path) as archive:
            archive.setpassword(export.password.encode("ascii"))
            assert archive.read("laya/candidates.train.jsonl") == candidate_payload
            report = json.loads(archive.read("laya/report.json"))
            assert report["candidate_text_export"]["status"] == "included"
            assert report["candidate_text_export"]["included_rows"] == 1
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["laya"]["candidate_text"]["status"] == "included"
            assert manifest["laya"]["candidate_text"]["included_rows"] == 1


def test_support_archive_reports_missing_laya_state_without_candidate_text(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with create_diagnostics_archive(state_dir, source_root=tmp_path / "no-source", temp_dir=tmp_path) as export:
        with pyzipper.AESZipFile(export.path) as archive:
            archive.setpassword(export.password.encode("ascii"))
            names = set(archive.namelist())
            assert "laya/report.json" in names
            assert "laya/candidates.train.jsonl" not in names
            report = json.loads(archive.read("laya/report.json"))
            assert report["schema_version"] == 1
            assert report["candidate_data_status"] == "unavailable"
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["laya"]["candidate_text"]["status"] == "omitted"
            assert manifest["laya"]["missing_data"]["candidate_database"] == 1
            assert manifest["laya"]["missing_data"]["shadow_telemetry"] == 1
            assert manifest["laya"]["missing_data"]["evaluation_report"] == 1
            assert manifest["laya"]["missing_data"]["backend_provenance"] == 1


def test_support_archive_reports_laya_runtime_metadata_without_hardware_claim(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    decisions = {
        "available": True,
        "counts_by_mode": {"shadow": 2, "advisory": 1},
        "by_mode": {
            "shadow": {
                "records": 2,
                "counts_by_category": {"context_strategy": 2},
                "counts_by_status": {"abstain": 1, "suggestion": 1},
                "counts_by_reason_code": {"insufficient_evidence": 1},
                "abstentions": 1,
                "errors": 0,
                "skips": 0,
                "coverage": {"available": False, "reason": "eligible_decision_count_not_recorded"},
            },
            "advisory": {"records": 1},
        },
    }
    runtime = {
        "available": False,
        "provider_close_configured": False,
        "runtime_verification": "NOT_VERIFIED",
    }

    with create_diagnostics_archive(
        state_dir,
        source_root=tmp_path / "no-source",
        temp_dir=tmp_path,
        laya_telemetry={"decisions": decisions, "runtime": runtime},
    ) as export:
        with pyzipper.AESZipFile(export.path) as archive:
            archive.setpassword(export.password.encode("ascii"))
            report = json.loads(archive.read("laya/report.json"))

    assert report["runtime"] == runtime
    assert report["shadow_telemetry"]["decisions"] == decisions


def test_support_archive_rejects_empty_laya_candidate_payload_and_cleans_up(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    with pytest.raises(ValueError, match="explicit Laya training export is empty or exceeds byte limit"):
        create_diagnostics_archive(
            state_dir,
            source_root=tmp_path / "no-source",
            temp_dir=tmp_path,
            laya_candidate_payload=b"",
        )

    assert list(tmp_path.glob("local-ai-hub-export-*")) == []
