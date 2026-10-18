from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub import async_jobs, services


def test_batch_delegate_rejects_more_than_sixteen_without_delegating(monkeypatch):
    calls = []
    self = SimpleNamespace(
        router=SimpleNamespace(classify=lambda *args: calls.append("classify")),
        scheduler=SimpleNamespace(status=lambda: {"active_model": None}),
        delegate=lambda *args: calls.append("delegate"),
    )
    monkeypatch.setattr(async_jobs, "report_job_progress", lambda *args: None)

    result = services.LocalAIServices.batch_delegate(
        self, {"tasks": [{"task": f"task-{i}"} for i in range(17)]}
    )

    assert calls == []
    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["request_not_sent"] is True
    assert result["input_count"] == 17
    assert result["accepted_count"] == 0
    assert result["rejected_count"] == 17
    assert result["rejected_indices"] == list(range(17))
    assert result["rejected_range"] == {"start": 0, "end_exclusive": 17}
    assert result["rejected_indices_truncated"] is False
    assert result["results"] == []


def test_batch_delegate_bounds_rejected_indices_for_huge_input():
    calls = []
    self = SimpleNamespace(
        router=SimpleNamespace(classify=lambda *args: calls.append("classify")),
        scheduler=SimpleNamespace(status=lambda: {"active_model": None}),
        delegate=lambda *args: calls.append("delegate"),
    )

    result = services.LocalAIServices.batch_delegate(self, {"tasks": [None] * 100_000})

    assert calls == []
    assert result["input_count"] == 100_000
    assert result["accepted_count"] == 0
    assert result["rejected_count"] == 100_000
    assert result["rejected_range"] == {"start": 0, "end_exclusive": 100_000}
    assert result["rejected_indices"] == list(range(64))
    assert result["rejected_indices_truncated"] is True


def test_batch_delegate_marks_empty_preflight_as_terminal_without_sending():
    calls = []
    self = SimpleNamespace(
        router=SimpleNamespace(classify=lambda *args: calls.append("classify")),
        scheduler=SimpleNamespace(status=lambda: {"active_model": None}),
        delegate=lambda *args: calls.append("delegate"),
    )

    result = services.LocalAIServices.batch_delegate(self, {"tasks": []})

    assert calls == []
    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["request_not_sent"] is True
    assert result["input_count"] == 0
    assert result["accepted_count"] == 0
    assert result["rejected_count"] == 0


def test_batch_delegate_reports_counts_for_every_accepted_task(monkeypatch):
    delegated = []
    self = SimpleNamespace(
        router=SimpleNamespace(classify=lambda *args: {"model": "model-a"}),
        scheduler=SimpleNamespace(status=lambda: {"active_model": "model-a"}),
        delegate=lambda item: delegated.append(item) or {"success": True},
    )
    monkeypatch.setattr(async_jobs, "report_job_progress", lambda *args: None)

    result = services.LocalAIServices.batch_delegate(
        self, {"tasks": [{"task": f"task-{i}"} for i in range(16)]}
    )

    assert len(delegated) == 16
    assert result["success"] is True
    assert result["input_count"] == 16
    assert result["accepted_count"] == 16
    assert result["rejected_count"] == 0
    assert result["rejected_indices"] == []
    assert len(result["results"]) == 16


def test_optimize_databases_counts_busy_checkpoint_as_partial_failure(monkeypatch, tmp_path):
    busy_db = tmp_path / "busy.sqlite"
    good_db = tmp_path / "good.sqlite"
    busy_db.write_bytes(b"busy database")
    good_db.write_bytes(b"good database")
    connections = []

    class Cursor:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self, busy):
            self.busy = busy
            self.closed = False

        def execute(self, sql):
            if "wal_checkpoint" in sql:
                return Cursor((self.busy, 0, 0))
            return Cursor(None)

        def close(self):
            self.closed = True

    def connect(db, timeout_seconds):
        connection = Connection(busy=db == busy_db)
        connections.append(connection)
        return connection

    monkeypatch.setattr(services, "_active_sqlite_databases", lambda state_dir: [busy_db, good_db])
    monkeypatch.setattr(services, "connect_sqlite", connect)
    self = SimpleNamespace(config={"server": {"state_dir": str(tmp_path)}})

    result = services.LocalAIServices.optimize_databases(self)

    assert result["success"] is False
    assert result["partial"] is True
    assert result["databases_attempted"] == 2
    assert result["databases_succeeded"] == 1
    assert result["databases_failed"] == 1
    assert result["databases_optimized"] == 1
    assert result["error"] == "1 of 2 database maintenance operations failed"
    assert result["details"][0]["success"] is False
    assert "WAL checkpoint remained busy" in result["details"][0]["error"]
    assert result["details"][1]["success"] is True
    assert all(connection.closed for connection in connections)
