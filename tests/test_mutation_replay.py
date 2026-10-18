from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import threading
from types import SimpleNamespace
from typing import Any
from urllib.error import URLError

import pytest
import sqlite3
from contextlib import closing
from contextlib import nullcontext

from local_ai_hub import http_server
from local_ai_hub.agent_events import AgentStateStore, SwarmPubSub
from local_ai_hub.client import HubClient
from local_ai_hub.commands import CommandBroker
from local_ai_hub.rag import RAGStore
from local_ai_hub.resilience import RecoveryJournal


def _broker(tmp_path) -> CommandBroker:
    return CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_mutating": True},
        },
        artifacts=None,
        repo_state=None,
    )


def _register_task_worktree(broker: CommandBroker, task_id: str, root) -> None:
    task = SimpleNamespace(
        checkpoint=SimpleNamespace(
            state_data={"worktree": {"worktree_path": str(root), "success": True}}
        )
    )
    broker.task_store = SimpleNamespace(get=lambda requested_id: task if requested_id == task_id else None)


def _use_test_transaction(broker: CommandBroker, monkeypatch, root) -> None:
    # These tests cover repair/replay policy; transaction lifecycle has its own tests.
    monkeypatch.setattr(broker, "_transaction_root_for_context", lambda _transaction_id: root)
    monkeypatch.setattr(
        broker,
        "_run_private_transaction",
        lambda **kwargs: kwargs["operation"](root, "test-transaction"),
    )


def test_repair_loop_replays_explicitly_safe_validation(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    _register_task_worktree(broker, "task-1", tmp_path)
    _use_test_transaction(broker, monkeypatch, tmp_path)
    command = "python -m pytest -q tests/test_example.py"
    executions: list[str] = []
    generated: list[str] = []

    monkeypatch.setattr(
        broker,
        "classify",
        lambda _command: {"class": "validation", "replay_safe": True},
    )
    monkeypatch.setattr(
        broker,
        "run",
        lambda cmd, *_args, **_kwargs: executions.append(cmd) or {"success": True},
    )

    def generate(cmd: str, *_args: Any) -> dict[str, str]:
        generated.append(cmd)
        return {"repair_candidate.txt": "candidate"}

    result = broker.repair_loop(
        command,
        tmp_path,
        task_id="task-1",
        max_attempts=1,
        paths=["repair_candidate.txt"],
        fix_generator=generate,
        initial_result={"success": False, "outcome_unknown": False},
    )

    assert result["success"] is True, result
    assert result["repaired"] is True
    assert executions == [command]
    assert generated == [command]


def test_repair_loop_does_not_replay_unclassified_validation(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    _register_task_worktree(broker, "task-1", tmp_path)
    _use_test_transaction(broker, monkeypatch, tmp_path)
    command = "python -m pytest -q tests/test_example.py"
    executions: list[str] = []
    generated: list[str] = []

    monkeypatch.setattr(broker, "classify", lambda _command: {"class": "validation"})
    monkeypatch.setattr(
        broker,
        "run",
        lambda cmd, *_args, **_kwargs: executions.append(cmd) or {"success": True},
    )
    result = broker.repair_loop(
        command,
        tmp_path,
        task_id="task-1",
        max_attempts=1,
        paths=["repair_candidate.txt"],
        fix_generator=lambda cmd, *_args: generated.append(cmd) or {"repair_candidate.txt": "candidate"},
        initial_result={"success": False, "outcome_unknown": False},
    )

    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert result["attempts"] == 0
    assert executions == []
    assert generated == []


def test_repair_loop_honors_explicit_replay_unsafe_classification(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    _register_task_worktree(broker, "task-1", tmp_path)
    _use_test_transaction(broker, monkeypatch, tmp_path)
    command = "powershell -NoProfile -Command Invoke-Pester"
    executions: list[str] = []
    generated: list[str] = []

    monkeypatch.setattr(
        broker,
        "classify",
        lambda _command: {"class": "validation", "replay_safe": False},
    )
    monkeypatch.setattr(
        broker,
        "run",
        lambda cmd, *_args, **_kwargs: executions.append(cmd) or {"success": True},
    )

    def generate(cmd: str, *_args: Any) -> dict[str, str]:
        generated.append(cmd)
        return {"repair_candidate.txt": "candidate"}

    result = broker.repair_loop(
        command,
        tmp_path,
        task_id="task-1",
        max_attempts=1,
        paths=["repair_candidate.txt"],
        fix_generator=generate,
        initial_result={"success": False, "outcome_unknown": False},
    )

    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert result["attempts"] == 0
    assert executions == []
    assert generated == []


def test_repair_loop_does_not_replay_failed_mutating_command(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    _register_task_worktree(broker, "task-1", tmp_path)
    _use_test_transaction(broker, monkeypatch, tmp_path)
    executions: list[str] = []
    generator_calls: list[str] = []

    def run(command: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        executions.append(command)
        return {"success": False, "exit_code": 1, "stderr": "partial mutation"}

    def generate(command: str, *_args: Any) -> dict[str, str]:
        generator_calls.append(command)
        return {"changed.py": "value = 1\n"}

    monkeypatch.setattr(broker, "run", run)

    result = broker.repair_loop(
        "git add changed.py",
        str(tmp_path),
        task_id="task-1",
        max_attempts=2,
        paths=["changed.py"],
        fix_generator=generate,
    )

    assert result["success"] is False
    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert executions == ["git add changed.py"]
    assert generator_calls == []


def test_repair_loop_stops_after_timed_out_command_outcome_is_unknown(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
    _register_task_worktree(broker, "task-1", tmp_path)
    _use_test_transaction(broker, monkeypatch, tmp_path)
    command = "python -m pytest -q"
    executions: list[str] = []
    generator_calls: list[str] = []

    def run(actual_command: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        executions.append(actual_command)
        return {
            "success": False,
            "timed_out": True,
            "outcome_unknown": True,
            "retryable": False,
            "error": "command timeout after execution began",
        }

    def generate(actual_command: str, *_args: Any) -> dict[str, str]:
        generator_calls.append(actual_command)
        return {"changed.py": "value = 1\n"}

    monkeypatch.setattr(broker, "run", run)

    result = broker.repair_loop(
        command,
        str(tmp_path),
        task_id="task-1",
        max_attempts=3,
        paths=["changed.py"],
        fix_generator=generate,
    )

    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert result["attempts"] == 0
    assert executions == [command]
    assert generator_calls == []


@pytest.mark.parametrize("status", [{"timed_out": True}, {"in_progress": True}])
def test_repair_loop_skips_timed_out_or_running_command(tmp_path, monkeypatch, status) -> None:
    broker = _broker(tmp_path)
    _register_task_worktree(broker, "task-1", tmp_path)
    _use_test_transaction(broker, monkeypatch, tmp_path)
    generator_calls: list[str] = []
    monkeypatch.setattr(broker, "run", lambda *_args, **_kwargs: pytest.fail("must not replay command"))
    result = broker.repair_loop(
        "python -m pytest -q",
        str(tmp_path),
        task_id="task-1",
        paths=["changed.py"],
        initial_result={"success": False, **status},
        fix_generator=lambda command, *_args: generator_calls.append(command) or {"changed.py": "value=1"},
    )

    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert result["attempts"] == 0
    assert generator_calls == []


def test_recovery_journal_replays_the_same_payload_after_response_loss(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {
        "root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1",
        "state": "done",
    }

    first = journal.begin("req-1", action="/api/agent-state/tasks", payload=payload)
    journal.finish("req-1", True, status_code=200, response={"success": True, "checkpoint_id": "cp-1"})
    retry = journal.begin("req-1", action="/api/agent-state/tasks", payload=payload)

    assert first["claimed"] is True
    assert retry["claimed"] is False
    assert retry["state"] == "done"
    assert retry["response"] == {"success": True, "checkpoint_id": "cp-1"}


def test_begin_requires_action_and_payload(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)

    with pytest.raises(TypeError):
        journal.begin("req-required", payload={"action": "submit"})
    with pytest.raises(TypeError):
        journal.begin("req-required", action="/api/work-orders")


def test_recovery_journal_conflicts_when_request_payload_changes(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    base = {"root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1"}
    journal.begin("req-1", action="/api/agent-state/tasks", payload={**base, "state": "done"})

    retry = journal.begin("req-1", action="/api/agent-state/tasks", payload={**base, "state": "failed"})

    assert retry["claimed"] is False
    assert retry["state"] == "conflict"


@pytest.mark.parametrize(
    "request_id",
    ["", " req-1", "req 1", "req\r\nInjected: yes", "\x7f", "r" * 129, "réq-1", None, 17],
)
def test_recovery_journal_rejects_invalid_request_ids_before_claim(tmp_path, request_id) -> None:
    journal = RecoveryJournal(tmp_path)

    with pytest.raises(ValueError, match="request_id"):
        journal.begin(request_id, action="/api/agent-state/tasks", payload={
            "root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1", "state": "done",
        })

    with closing(sqlite3.connect(journal.path)) as con:
        count = con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    assert count == 0


def test_wait_for_preserves_unknown_after_process_interruption(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"root": str(tmp_path.resolve()), "task_id": "task-1", "action": "submit"}
    journal.begin("req-1", action="/api/work-orders", payload=payload)
    journal.mark_interrupted_on_startup()

    result = journal.wait_for(
        "req-1", action="/api/work-orders", payload_fingerprint=journal.fingerprint_payload(payload),
        timeout_seconds=0.01,
    )

    assert result is not None
    assert result["state"] == "abandoned"
    assert result["outcome_unknown"] is True


def test_lookup_requires_action_and_payload_fingerprint(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1"}
    journal.begin("req-identity", action="/api/work-orders", payload=payload)
    journal.finish("req-identity", True, response={"secret": "stored"})
    fingerprint = journal.fingerprint_payload(payload)

    with pytest.raises(TypeError):
        journal.lookup("req-identity", payload_fingerprint=fingerprint)
    with pytest.raises(TypeError):
        journal.lookup("req-identity", action="/api/work-orders")

    assert journal.lookup(
        "req-identity", action="/api/other", payload_fingerprint=fingerprint
    )["state"] == "conflict"
    assert journal.lookup(
        "req-identity", action="/api/work-orders", payload_fingerprint="different"
    )["state"] == "conflict"


def test_wait_for_requires_action_and_payload_fingerprint(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1"}
    journal.begin("req-wait-identity", action="/api/work-orders", payload=payload)
    fingerprint = journal.fingerprint_payload(payload)

    with pytest.raises(TypeError):
        journal.wait_for("req-wait-identity", timeout_seconds=0, payload_fingerprint=fingerprint)
    with pytest.raises(TypeError):
        journal.wait_for("req-wait-identity", action="/api/work-orders", timeout_seconds=0)

    journal.finish("req-wait-identity", True, response={"secret": "stored"})
    action_mismatch = journal.wait_for(
        "req-wait-identity", action="/api/other", timeout_seconds=0,
        payload_fingerprint=fingerprint,
    )
    payload_mismatch = journal.wait_for(
        "req-wait-identity", action="/api/work-orders", timeout_seconds=0,
        payload_fingerprint="different",
    )
    assert action_mismatch["state"] == "conflict"
    assert payload_mismatch["state"] == "conflict"
    assert action_mismatch["error"]
    assert payload_mismatch["error"]


def test_trusted_lookup_metadata_never_returns_stored_response(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1"}
    journal.begin("req-trace-metadata", action="/api/work-orders", payload=payload)
    journal.finish("req-trace-metadata", True, response={"secret": "stored"})

    metadata = journal.lookup_metadata(
        "req-trace-metadata", action="/api/work-orders"
    )

    assert metadata["state"] == "done"
    assert "response" not in metadata


def test_debug_trace_reconciliation_uses_trusted_journal_metadata(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    journal.begin(
        "req-trace-reconcile",
        action="/api/work-orders",
        payload={"root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1"},
    )
    journal.finish("req-trace-reconcile", True, response={"success": True})
    reconciled: list[tuple[str, dict[str, Any]]] = []
    trace_store = SimpleNamespace(
        reconcile_terminal=lambda trace_id, **kwargs: reconciled.append((trace_id, kwargs))
    )
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(recovery=journal, debug_traces=trace_store),
    )
    trace = {
        "trace_id": "trace-1",
        "request_id": "req-trace-reconcile",
        "action": "/api/work-orders",
        "state": "running",
    }

    result = http_server.Handler._reconcile_debug_trace(None, trace)

    assert result["state"] == "done"
    assert reconciled == [("trace-1", {"state": "done", "response": None, "error": ""})]


@pytest.mark.parametrize(
    ("action", "field", "value"),
    [
        ("wait", "timeout_seconds", "1"),
        ("wait", "timeout_seconds", -1),
        ("wait", "timeout_seconds", 91),
        ("wait", "timeout_seconds", True),
        ("wait", "timeout_seconds", float("nan")),
        ("get", "max_output_tokens", 1.5),
        ("get", "max_output_tokens", -1),
        ("get", "max_output_tokens", 4097),
        ("submit", "max_output_tokens", True),
    ],
)
def test_work_order_numeric_controls_are_validated_before_dispatch(action, field, value) -> None:
    payload = {"action": action}
    if action == "submit":
        payload.update({"root": ".", "task": "bounded numeric validation"})
    else:
        payload["work_id"] = "work-1"
    payload[field] = value

    with pytest.raises(http_server.RequestBodyError):
        http_server.Handler._validate_payload("/api/work-orders", payload)


def test_invalid_work_order_body_is_rejected_before_mutation_dispatch(monkeypatch) -> None:
    payload = {
        "action": "submit", "root": ".", "task": "bounded numeric validation",
        "max_output_tokens": True,
    }
    submitted: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={},
        recovery=SimpleNamespace(
            fingerprint_payload=lambda _payload: "fingerprint",
            begin=lambda *_args, **_kwargs: {"claimed": True, "state": "running"},
            finish=lambda *_args, **_kwargs: None,
        ),
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda request: submitted.append(dict(request)) or {"success": True},
        ),
    )
    responses: list[tuple[int, dict[str, Any]]] = []
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(
        http_server.Handler,
        "_begin_trace",
        lambda self, _path: setattr(self, "_trace_request_id", "req-invalid"),
    )
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: dict(payload))
    monkeypatch.setattr(
        http_server.Handler,
        "_send",
        lambda self, status, data: responses.append((status, data)),
    )
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/work-orders"
    handler.headers = {"Content-Type": "application/json"}

    http_server.Handler.do_POST(handler)

    assert submitted == []
    assert responses[0][0] == 400
    assert responses[0][1]["terminal"] is True
    assert responses[0][1]["retryable"] is False


@pytest.mark.parametrize(
    ("action", "identity_changes"),
    [
        ("/api/agent-state/tasks", {"task_id": "task-other"}),
        ("/api/agent-state/task/cleanup", {}),
        ("/api/agent-state/tasks", {"session_id": "session-other"}),
    ],
)
def test_recovery_journal_binds_request_to_operation_and_repository_task_session(
    tmp_path, action: str, identity_changes: dict[str, str],
) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {
        "root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1", "state": "done",
    }
    journal.begin("req-1", action="/api/agent-state/tasks", payload=payload)

    retry = journal.begin("req-1", action=action, payload={**payload, **identity_changes})

    assert retry["claimed"] is False
    assert retry["state"] == "conflict"


def test_recovery_journal_claim_is_atomic_across_clients(tmp_path) -> None:
    journals = [RecoveryJournal(tmp_path), RecoveryJournal(tmp_path)]
    payload = {
        "root": str(tmp_path.resolve()), "task_id": "task-rag-1", "session_id": "session-rag-1",
        "document_id": "doc-1", "content": "stable",
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda journal: journal.begin(
                "req-1", action="/api/rag/ingest_document", payload=payload,
            ),
            journals,
        ))

    assert sum(bool(result["claimed"]) for result in results) == 1
    assert {result["state"] for result in results} == {"running"}


def test_recovery_journal_process_crash_stays_explicitly_unknown(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"root": str(tmp_path.resolve()), "task_id": "task-1", "session_id": "session-1", "action": "submit"}
    journal.begin("req-1", action="/api/work-orders", payload=payload)

    restarted = RecoveryJournal(tmp_path)
    retry = restarted.begin("req-1", action="/api/work-orders", payload=payload)

    assert retry["claimed"] is False
    assert retry["state"] == "abandoned"
    assert retry["outcome_unknown"] is True


def test_corrupt_journal_rebuild_never_claims_mutations(tmp_path) -> None:
    (tmp_path / "recovery.sqlite3").write_bytes(b"not a sqlite database")

    first_process = RecoveryJournal(tmp_path)
    assert (tmp_path / "recovery.unavailable").exists()
    with pytest.raises(sqlite3.DatabaseError, match="refusing mutation dispatch"):
        first_process.begin("req-1", action="/api/command", payload={"root": str(tmp_path.resolve()), "task_id": "task-1", "command": "deploy"})

    restarted_process = RecoveryJournal(tmp_path)
    with pytest.raises(sqlite3.DatabaseError, match="refusing mutation dispatch"):
        restarted_process.begin("req-1", action="/api/command", payload={"root": str(tmp_path.resolve()), "task_id": "task-1", "command": "deploy"})


def test_unsupported_legacy_journal_is_preserved_and_fails_closed(tmp_path) -> None:
    path = tmp_path / "recovery.sqlite3"
    with closing(sqlite3.connect(path)) as con:
        con.execute("""
            CREATE TABLE requests (
                request_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, action TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                detail TEXT NOT NULL DEFAULT '', status_code INTEGER NOT NULL DEFAULT 0,
                response_json TEXT NOT NULL DEFAULT ''
            )
        """)
        con.execute(
            "INSERT INTO requests(request_id,tenant,action,state,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("req-legacy", "tenant", "/api/command", "running", 1.0, 1.0),
        )
        con.commit()
    original = path.read_bytes()

    journal = RecoveryJournal(tmp_path)

    assert journal._journal_unavailable is True
    assert path.read_bytes() == original
    with closing(sqlite3.connect(path)) as con:
        assert con.execute("SELECT request_id,state FROM requests").fetchall() == [("req-legacy", "running")]
    with pytest.raises(sqlite3.DatabaseError, match="refusing mutation dispatch"):
        journal.begin("req-new", action="/api/command", payload={"root": str(tmp_path.resolve()), "task_id": "task-1", "command": "safe"})


def test_response_is_journaled_before_a_client_disconnect(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {
        "action": "submit", "work_id": "work-1", "root": str(tmp_path.resolve()),
        "task_id": "task-disconnect-1", "session_id": "session-disconnect-1",
    }
    journal.begin("req-1", action="/api/work-orders", payload=payload)

    class _DisconnectedWriter:
        def write(self, _body: bytes) -> None:
            raise BrokenPipeError("client disconnected before reading response")

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(recovery=journal))
    monkeypatch.setattr(http_server.Handler, "_finish_debug_trace", lambda self, *_args, **_kwargs: None)
    monkeypatch.setattr(http_server.Handler, "_close_trace_context", lambda self: None)
    monkeypatch.setattr(http_server.Handler, "_common_headers", lambda self, **_kwargs: None)
    monkeypatch.setattr(http_server.Handler, "send_response", lambda self, _status: None)
    monkeypatch.setattr(http_server.Handler, "send_header", lambda self, _key, _value: None)
    monkeypatch.setattr(http_server.Handler, "end_headers", lambda self: None)
    handler = object.__new__(http_server.Handler)
    handler.headers = {}
    handler._journal_request_id = "req-1"
    handler._journal_finished = False
    handler._telemetry_finished = True
    handler._debug_trace_finished = True
    handler.path = "/api/work-orders"
    handler.wfile = _DisconnectedWriter()

    try:
        handler._send(200, {"success": True, "work_id": "work-1"})
    except BrokenPipeError:
        pass

    replay = journal.lookup(
        "req-1", action="/api/work-orders",payload_fingerprint=journal.fingerprint_payload(payload),
    )
    assert replay is not None
    assert replay["state"] == "done"
    assert replay["response"] == {"success": True, "work_id": "work-1", "request_id": "req-1"}
    assert replay["response"]["request_id"] == "req-1"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/rag/index", {"root": "project"}),
        ("/api/rag/ingest_document", {"document_id": "doc-1"}),
        ("/api/work-orders", {"action": "submit", "work_id": "work-1"}),
        ("/api/agent-state/tasks", {"action": "checkpoint", "task_id": "task-1"}),
        ("/api/command", {"command": "pytest"}),
    ],
)
def test_failed_partial_publish_is_replayed_without_reexecution(tmp_path, path: str, payload: dict[str, Any]) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {
        **payload,
        "root": str(tmp_path.resolve()),
        "task_id": str(payload.get("task_id") or "task-replay-1"),
        "session_id": "session-replay-1",
    }
    calls: list[str] = []
    claimed = journal.begin("req-1", action=path,payload=payload)
    assert claimed["claimed"] is True

    calls.append("publish began; later stage failed")
    failure = {"success": False, "error": "publish interrupted", "partial_publish": True}
    journal.finish("req-1", False, status_code=500, response=failure)
    retry = journal.begin("req-1", action=path,payload=payload)

    assert calls == ["publish began; later stage failed"]
    assert retry["claimed"] is False
    assert retry["state"] == "failed"
    assert retry["response"] == failure


def test_rag_index_publish_failure_keeps_previous_snapshot(tmp_path) -> None:
    class _EmbeddingServices:
        def embed(self, texts, **_kwargs):
            return {"success": True, "embeddings": [[1.0, 0.0] for _ in texts]}

    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py"], "ignore_dirs": [], "chunk_chars": 4096, "chunk_overlap_chars": 0, "rerank_candidates": 8},
            "features": {"reranker": False},
        },
        _EmbeddingServices(),
        None,
    )
    root = tmp_path / "project"
    root.mkdir()
    source = root / "one.py"
    source.write_text("def value():\n    return 'old snapshot'\n", encoding="utf-8")
    first = store.index(root=str(root))
    assert first["success"] is True
    workspace = store.workspace_id(str(root))
    with closing(store._connect()) as con:
        old_file_hash = con.execute(
            "SELECT content_hash FROM files WHERE workspace=? AND path=?",
            (workspace, "one.py"),
        ).fetchone()[0]

    with closing(store._connect()) as con:
        con.execute(
            "CREATE TRIGGER fail_rag_publish BEFORE INSERT ON chunks "
            "WHEN NEW.path='one.py' BEGIN SELECT RAISE(ABORT, 'injected publish failure'); END"
        )
        con.commit()
    source.write_text("def value():\n    return 'new snapshot'\n", encoding="utf-8")

    try:
        second = store.index(root=str(root), workspace=workspace)
    except sqlite3.DatabaseError:
        second = {"success": False}

    assert second["success"] is False
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT text FROM chunks WHERE workspace=?",
            (workspace,),
        ).fetchall()
        file_hash = con.execute(
            "SELECT content_hash FROM files WHERE workspace=? AND path=?",
            (workspace, "one.py"),
        ).fetchone()[0]
    assert rows
    assert all("old snapshot" in row[0] for row in rows)
    assert file_hash == old_file_hash


def test_client_allows_explicit_retry_with_the_same_request_id(tmp_path, monkeypatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    seen_request_ids: list[str] = []

    def open_request(_method: str, _path: str, _body: bytes, headers: dict[str, str], _timeout: float) -> bytes:
        seen_request_ids.append(headers["X-LocalAI-Request-ID"])
        return b'{"success":true,"checkpoint_id":"cp-1"}'

    monkeypatch.setattr(client, "_pooled_open", open_request)
    first = client.post("/api/tasks/checkpoint", {"task_id": "task-1"}, request_id="t07-checkpoint-1")
    retry = client.post("/api/tasks/checkpoint", {"task_id": "task-1"}, request_id="t07-checkpoint-1")

    assert first == retry == {"success": True, "checkpoint_id": "cp-1"}
    assert seen_request_ids == ["t07-checkpoint-1", "t07-checkpoint-1"]


def test_client_safe_transport_retry_reuses_request_id(tmp_path, monkeypatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    seen_request_ids: list[str] = []

    def open_request(_method: str, _path: str, _body: bytes, headers: dict[str, str], _timeout: float) -> bytes:
        seen_request_ids.append(headers["X-LocalAI-Request-ID"])
        if len(seen_request_ids) == 1:
            raise URLError("connection refused before request dispatch")
        return b'{"success":true,"checkpoint_id":"cp-1"}'

    monkeypatch.setattr(client, "_pooled_open", open_request)
    result = client.post(
        "/api/repo/complexity",
        {"root": str(tmp_path)},
        request_id="t07-pre-send-retry-1",
    )

    assert result == {"success": True, "checkpoint_id": "cp-1"}
    assert seen_request_ids == ["t07-pre-send-retry-1", "t07-pre-send-retry-1"]


@pytest.mark.parametrize("request_id", ["", "bad request", "bad\nid", "café"])
def test_client_rejects_malformed_request_id_before_network(tmp_path, monkeypatch, request_id: str) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    sent: list[str] = []
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: sent.append("sent") or b'{"success":true}')

    result = client.post("/api/tasks/checkpoint", {"task_id": "task-1"}, request_id=request_id)

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert sent == []


def test_client_accepts_visible_ascii_request_id(tmp_path, monkeypatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    seen_request_ids: list[str] = []

    def open_request(_method: str, _path: str, _body: bytes, headers: dict[str, str], _timeout: float) -> bytes:
        seen_request_ids.append(headers["X-LocalAI-Request-ID"])
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", open_request)
    result = client.post("/api/tasks/checkpoint", {"task_id": "task-1"}, request_id="checkpoint!one")

    assert result == {"success": True}
    assert seen_request_ids == ["checkpoint!one"]


def test_mutation_transport_error_returns_explicit_uncertainty(tmp_path, monkeypatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)

    def connection_lost(*_args: Any, **_kwargs: Any) -> bytes:
        raise RuntimeError("transport failed after request write")

    monkeypatch.setattr(client, "_pooled_open", connection_lost)
    result = client.post("/api/command", {"command": "deploy"}, request_id="t07-command-1")

    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert result["request_id"] == "t07-command-1"


def test_client_replay_safe_coalescing_timeout_returns_owner_request_id(tmp_path, monkeypatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=39123\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    request_started = threading.Event()
    release_request = threading.Event()
    seen_request_ids: list[str] = []

    def open_request(_method: str, _path: str, _body: bytes, headers: dict[str, str], _timeout: float) -> bytes:
        seen_request_ids.append(headers["X-LocalAI-Request-ID"])
        request_started.set()
        release_request.wait(0.4)
        return b'{"success":true}'

    monkeypatch.setattr(client, "_pooled_open", open_request)
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner = pool.submit(client.post, "/api/repo/complexity", {}, 1.0)
        assert request_started.wait(1.0)
        try:
            waiter = client.post("/api/repo/complexity", {}, timeout=0.02)
        finally:
            release_request.set()
        assert owner.result(timeout=1.0)["success"] is True

    assert waiter["success"] is False
    assert waiter["outcome_unknown"] is True
    assert waiter["in_progress"] is True
    assert waiter["retry_timeout"] is True
    assert waiter["retryable"] is True
    assert waiter["request_id"] == seen_request_ids[0]
    assert len(seen_request_ids) == 1


def test_maintenance_get_routes_are_read_only(tmp_path, monkeypatch) -> None:
    services = SimpleNamespace(
        optimize_databases=lambda: pytest.fail("GET must not optimize databases"),
        purge_stale_cache=lambda _days: pytest.fail("GET must not purge cache"),
        resolve_all_errors=lambda: pytest.fail("GET must not resolve errors"),
    )
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(
        config={"server": {"state_dir": str(tmp_path)}}, services=services
    ))
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: None)
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    responses: list[tuple[int, dict[str, Any], dict[str, str]]] = []
    monkeypatch.setattr(
        http_server.Handler,
        "_send",
        lambda self, status, data, **kwargs: responses.append((status, data, kwargs.get("headers", {}))),
    )

    for path in (
        "/api/maintenance/optimize_db",
        "/api/maintenance/purge_cache?days=7",
        "/api/maintenance/resolve_errors",
    ):
        handler = object.__new__(http_server.Handler)
        handler.path = path
        handler.headers = {}
        http_server.Handler.do_GET(handler)

    assert [status for status, _data, _headers in responses] == [405, 405, 405]
    assert all(headers == {"Allow": "POST"} for _status, _data, headers in responses)


def test_post_journal_failure_prevents_mutation_dispatch(monkeypatch) -> None:
    class _UnavailableJournal:
        @staticmethod
        def fingerprint_payload(_payload: Any) -> str:
            return "fingerprint"

        @staticmethod
        def begin(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise OSError("journal unavailable")

    submitted: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={},
        recovery=_UnavailableJournal(),
        async_jobs=SimpleNamespace(inference_admission=lambda _action: nullcontext()),
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda payload: submitted.append(payload) or {"success": True},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-1"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: {"action": "submit", "work_id": "work-1"})
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []
    monkeypatch.setattr(http_server.Handler, "_send", lambda self, status, data: responses.append((status, data)))
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/work-orders"
    handler.headers = {"Content-Type": "application/json"}

    http_server.Handler.do_POST(handler)

    assert submitted == []
    assert responses[0][0] == 503
    assert responses[0][1]["outcome_unknown"] is False


def test_post_work_order_disabled_gate_prevents_dispatch(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"action": "submit", "work_id": "work-disabled"}
    submitted: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={},
        recovery=journal,
        work_orchestrator=SimpleNamespace(
            enabled=False,
            submit=lambda request: submitted.append(dict(request)) or {"success": True},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-disabled"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: dict(payload))
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, data: dict[str, Any]) -> None:
        if not getattr(self, "_journal_finished", False):
            journal.finish("req-disabled", status < 400, status_code=status, response=data)
            self._journal_finished = True
        responses.append((status, data))

    monkeypatch.setattr(http_server.Handler, "_send", respond)
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/work-orders"
    handler.headers = {"Content-Type": "application/json"}

    http_server.Handler.do_POST(handler)

    assert submitted == []
    assert responses[0][0] == 403
    assert responses[0][1]["terminal"] is True
    assert responses[0][1]["error"] == "work orchestrator is disabled"


def test_http_retry_replays_outcome_and_rejects_changed_payload(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    payload_box: dict[str, dict[str, Any]] = {"value": {"action": "submit", "work_id": "work-1"}}
    original_payload = dict(payload_box["value"])
    submitted: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={},
        recovery=journal,
        async_jobs=SimpleNamespace(inference_admission=lambda _action: nullcontext()),
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda payload: submitted.append(dict(payload)) or {"success": True, "work_id": payload["work_id"]},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-1"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: dict(payload_box["value"]))
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, data: dict[str, Any]) -> None:
        if not getattr(self, "_journal_finished", False):
            journal.finish("req-1", status < 400, status_code=status, response=data)
            self._journal_finished = True
        responses.append((status, data))

    monkeypatch.setattr(http_server.Handler, "_send", respond)

    def request() -> None:
        handler = object.__new__(http_server.Handler)
        handler.path = "/api/work-orders"
        handler.headers = {"Content-Type": "application/json"}
        http_server.Handler.do_POST(handler)

    request()
    request()
    payload_box["value"] = {"action": "submit", "work_id": "different-work"}
    request()

    assert submitted == [{"action": "submit", "work_id": "work-1"}]
    assert [status for status, _data in responses] == [200, 200, 409]
    assert responses[1][1] == responses[0][1]
    original = journal.lookup(
        "req-1", action="/api/work-orders",payload_fingerprint=journal.fingerprint_payload(original_payload),
    )
    changed = journal.lookup(
        "req-1", action="/api/work-orders",payload_fingerprint=journal.fingerprint_payload(payload_box["value"]),
    )
    assert original["response"] == responses[0][1]
    assert changed == {"state": "conflict", "error": "request id already belongs to a different operation or payload"}


def test_http_retry_agent_metadata_does_not_partition_request_journal(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    agent_box = {"value": "agent-a"}
    payload = {
        "action": "submit", "root": str(tmp_path.resolve()),
        "task_id": "task-1", "session_id": "session-1", "work_id": "work-1",
    }
    submitted: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={},
        recovery=journal,
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda request: submitted.append(dict(request)) or {"success": True},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-identity"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: dict(payload))
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, data: dict[str, Any]) -> None:
        if not getattr(self, "_journal_finished", False):
            journal.finish("req-identity", status < 400, status_code=status, response=data)
            self._journal_finished = True
        responses.append((status, data))

    monkeypatch.setattr(http_server.Handler, "_send", respond)

    def request() -> None:
        handler = object.__new__(http_server.Handler)
        handler.path = "/api/work-orders"
        handler.headers = {"Content-Type": "application/json", "X-LocalAI-Agent": agent_box["value"]}
        http_server.Handler.do_POST(handler)

    request()
    agent_box["value"] = "agent-b"
    request()

    assert submitted == [payload]
    assert [status for status, _data in responses] == [200, 200]
    assert responses[1] == responses[0]

def test_http_retry_from_two_live_clients_dispatches_once(tmp_path, monkeypatch) -> None:
    from http.client import HTTPConnection
    import logging

    journal = RecoveryJournal(tmp_path)
    payload = {"action": "submit", "root": str(tmp_path), "task": "live HTTP idempotence"}
    publish_started = threading.Event()
    release_publish = threading.Event()
    duplicate_waiting = threading.Event()
    handler_started = threading.Event()
    journal_begin_started = threading.Event()
    journal_begin_finished = threading.Event()
    journal_begin_result: dict[str, Any] = {}
    submissions: list[dict[str, Any]] = []

    def submit(value: dict[str, Any]) -> dict[str, Any]:
        submissions.append(dict(value))
        publish_started.set()
        if not release_publish.wait(10.0):
            raise TimeoutError("test did not release first publication")
        return {"success": True, "work_id": "live-work-one"}

    telemetry = SimpleNamespace(record_live=lambda **_kwargs: None, record_http=lambda **_kwargs: None)
    app = SimpleNamespace(
        # Keep replay wait above the 5s synchronization barrier for loaded CI.
        config={"resilience": {"singleflight_wait_timeout_seconds": 10.0}, "observability": {}},
        recovery=journal,
        telemetry=telemetry,
        logger=logging.getLogger("test.http-idempotence"),
        work_orchestrator=SimpleNamespace(enabled=True, submit=submit),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)

    original_do_post = http_server.Handler.do_POST

    def observed_do_post(self) -> None:
        handler_started.set()
        original_do_post(self)

    monkeypatch.setattr(http_server.Handler, "do_POST", observed_do_post)

    original_begin = journal.begin

    def observed_begin(*args: Any, **kwargs: Any) -> dict[str, Any]:
        journal_begin_started.set()
        try:
            result = original_begin(*args, **kwargs)
            journal_begin_result.update({"claimed": result.get("claimed"), "state": result.get("state")})
            return result
        except Exception as exc:
            journal_begin_result["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            journal_begin_finished.set()

    monkeypatch.setattr(journal, "begin", observed_begin)

    wait_for = journal.wait_for

    def observed_wait(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        duplicate_waiting.set()
        return wait_for(*args, **kwargs)

    monkeypatch.setattr(journal, "wait_for", observed_wait)

    server = http_server.ThreadingHTTPServer(("127.0.0.1", 0), http_server.Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address

    def send_request() -> tuple[int, dict[str, Any]]:
        connection = HTTPConnection(host, port, timeout=10.0)
        try:
            connection.request(
                "POST",
                "/api/work-orders",
                body=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-LocalAI-Request-ID": "req-live-two-clients",
                },
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_client = pool.submit(send_request)
            if not publish_started.wait(10.0):
                first_result: Any = "pending"
                if first_client.done():
                    try:
                        first_result = first_client.result()
                    except Exception as exc:
                        first_result = f"{type(exc).__name__}: {exc}"
                raise AssertionError(
                    "live HTTP request did not reach submit callback; "
                    f"handler_started={handler_started.is_set()}, "
                    f"journal_begin_started={journal_begin_started.is_set()}, "
                    f"journal_begin_finished={journal_begin_finished.is_set()}, "
                    f"journal_begin_result={journal_begin_result!r}, "
                    f"first_client={first_result!r}"
                )
            second_client = pool.submit(send_request)
            try:
                assert duplicate_waiting.wait(5.0)
            finally:
                release_publish.set()
            first_response = first_client.result(timeout=10.0)
            second_response = second_client.result(timeout=10.0)
    finally:
        release_publish.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5.0)

    expected = (200, {"success": True, "work_id": "live-work-one", "request_id": "req-live-two-clients"})
    assert submissions == [payload]
    assert first_response == second_response == expected
    assert first_response[1]["request_id"] == "req-live-two-clients"
    assert second_response[1]["request_id"] == "req-live-two-clients"
    assert not server_thread.is_alive()

def test_http_retry_after_response_loss_publishes_one_durable_event(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path / "recovery")
    state_store = AgentStateStore(tmp_path / "agent-state.sqlite3")
    pubsub = SwarmPubSub(state_store)
    payload_box: dict[str, dict[str, Any]] = {
        "value": {"topic": "t07-idempotence", "message": {"operation_id": "publish-1"}, "sender": "agent-a"}
    }
    original_payload = dict(payload_box["value"])
    app = SimpleNamespace(
        config={},
        recovery=journal,
        services=SimpleNamespace(pubsub_publish=pubsub.publish),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-publish-1"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: dict(payload_box["value"]))
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    lost_response: list[tuple[int, dict[str, Any]]] = []
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, data: dict[str, Any], headers: Any = None) -> None:
        if not getattr(self, "_journal_finished", False):
            journal.finish(self._journal_request_id, status < 400, status_code=status, response=data)
            self._journal_finished = True
            if not lost_response:
                lost_response.append((status, dict(data)))
                return  # Simulate a disconnect after the durable mutation and journal commit.
        responses.append((status, dict(data)))

    monkeypatch.setattr(http_server.Handler, "_send", respond)

    def request() -> None:
        handler = object.__new__(http_server.Handler)
        handler.path = "/api/coord/pubsub_publish"
        handler.headers = {"Content-Type": "application/json"}
        http_server.Handler.do_POST(handler)

    request()  # Mutation commits; response is lost.
    request()  # Same request ID replays the stored response.
    payload_box["value"] = {"topic": "t07-idempotence", "message": {"operation_id": "publish-2"}, "sender": "agent-a"}
    request()  # Changed payload conflicts before dispatch.

    with closing(sqlite3.connect(state_store.db_path)) as con:
        durable_events = con.execute(
            "SELECT seq, payload FROM agent_events WHERE stream_id = ? ORDER BY seq",
            ("pubsub:t07-idempotence",),
        ).fetchall()
    assert len(durable_events) == 1
    assert durable_events[0][0] == 1
    assert json.loads(durable_events[0][1]) == {
        "sender": "agent-a",
        "message": {"operation_id": "publish-1"},
    }
    assert [status for status, _data in responses] == [200, 409]
    assert responses[0] == lost_response[0]
    assert responses[1][1]["success"] is False
    stored = journal.lookup(
        "req-publish-1", action="/api/coord/pubsub_publish",payload_fingerprint=journal.fingerprint_payload(original_payload),
    )
    assert stored["response"] == lost_response[0][1]


def test_post_rejects_malformed_request_id_before_mutation_dispatch(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    submitted: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={"observability": {"exclude_http_paths": ["/api/work-orders"]}},
        recovery=journal,
        async_jobs=SimpleNamespace(inference_admission=lambda _action: nullcontext()),
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda payload: submitted.append(payload) or {"success": True},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: {"action": "submit", "work_id": "work-1"})
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []
    monkeypatch.setattr(http_server.Handler, "_send", lambda self, status, data, **_kwargs: responses.append((status, data)))
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/work-orders"
    handler.headers = {"Content-Type": "application/json", "X-LocalAI-Request-ID": "bad request id"}

    try:
        http_server.Handler.do_POST(handler)
    finally:
        if getattr(handler, "_trace_context_token", None) is not None:
            handler._close_trace_context()

    assert submitted == []
    assert responses[0][0] == 400
    assert responses[0][1]["terminal"] is True
    assert responses[0][1]["retryable"] is False
    assert "request_id" in responses[0][1]["error"]
    with closing(journal._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


def test_send_normalizes_http_error_before_journaling_and_serializing(monkeypatch) -> None:
    finished: list[dict[str, Any]] = []

    class _Recovery:
        def finish(self, _request_id, success, detail, *, status_code, response):
            finished.append({"success": success, "detail": detail, "status_code": status_code, "response": response})

    monkeypatch.setattr(http_server, "APP", SimpleNamespace(recovery=_Recovery()))
    monkeypatch.setattr(http_server.Handler, "_finish_debug_trace", lambda self, _status, _data: None)
    monkeypatch.setattr(http_server.Handler, "_common_headers", lambda self, **_kwargs: None)
    monkeypatch.setattr(http_server.Handler, "send_response", lambda self, _status: None)
    monkeypatch.setattr(http_server.Handler, "send_header", lambda self, _name, _value: None)
    monkeypatch.setattr(http_server.Handler, "end_headers", lambda self: None)
    handler = object.__new__(http_server.Handler)
    handler.headers = {}
    handler._journal_request_id = "req-send-error"
    handler._journal_finished = False
    handler._telemetry_finished = True
    handler._debug_trace_finished = True
    handler.path = "/api/work-orders"
    handler.wfile = BytesIO()

    http_server.Handler._send(handler, 503, {"error": "retry later"})

    expected = {
        "error": "retry later",
        "success": False,
        "status_code": 503,
        "retryable": True,
        "terminal": False,
        "request_id": "req-send-error",
    }
    assert finished[0]["success"] is False
    assert finished[0]["status_code"] == 503
    assert finished[0]["response"] == expected
    assert finished[0]["response"]["request_id"] == "req-send-error"
    assert json.loads(handler.wfile.getvalue().decode("utf-8")) == expected
    assert json.loads(handler.wfile.getvalue().decode("utf-8"))["request_id"] == "req-send-error"


@pytest.mark.parametrize(
    ("path", "payload", "expected_call"),
    [
        ("/api/rag/index", {"root": "project"}, "rag-index"),
        ("/api/rag/docset/index", {"name": "docs", "root": "project"}, "rag-docset-index"),
        ("/api/rag/ingest_document", {"workspace": "default", "content": "doc"}, "rag-ingest"),
        ("/api/rag/ingest_diagram", {"workspace": "default", "image_path": "diagram.png"}, "rag-diagram"),
        ("/api/work-orders", {"action": "submit", "work_id": "work-1"}, "work-submit"),
        ("/api/agent-state/tasks", {"action": "checkpoint", "task_id": "task-1", "checkpoint": {"phase": "testing", "next_action": "verify"}}, "task-checkpoint"),
        ("/api/command", {"command": "pytest"}, "command"),
    ],
)
def test_http_partial_publish_failure_replays_without_dispatching_twice(
    tmp_path, monkeypatch, path: str, payload: dict[str, Any], expected_call: str
) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = dict(payload)
    task_root = str(tmp_path.resolve())
    session_id = "session-journal-replay"
    payload["root"] = task_root
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    from local_ai_hub.project_config import resolve_project_context

    coordination_id = resolve_project_context(task_root, state_dir).coordination_id
    task = SimpleNamespace(
        context=SimpleNamespace(repository_id=coordination_id, session_id=session_id),
        checkpoint=SimpleNamespace(state_data={
            "_agent_task_scope": {"version": 2, "repo_root": task_root},
        }),
    )
    calls: list[str] = []

    def failed_publish(label: str) -> dict[str, Any]:
        calls.append(label)
        return {"success": False, "error": "partial publish", "partial_publish": True}

    def failed_checkpoint(*_args: Any, **_kwargs: Any) -> Any:
        calls.append("task-checkpoint")
        raise KeyError("checkpoint failed after partial publish")

    app = SimpleNamespace(
        config={"security": {
            "allowed_roots": [task_root],
        }},
        agent_state=SimpleNamespace(db_path=str(state_dir / "agent_state.sqlite3")),
        recovery=journal,
        async_jobs=SimpleNamespace(inference_admission=lambda _action: nullcontext()),
        rag=SimpleNamespace(
            index=lambda *_args, **_kwargs: failed_publish("rag-index"),
            docset_index=lambda *_args, **_kwargs: failed_publish("rag-docset-index"),
            ingest_document=lambda *_args, **_kwargs: failed_publish("rag-ingest"),
            ingest_diagram=lambda *_args, **_kwargs: failed_publish("rag-diagram"),
        ),
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda *_args, **_kwargs: failed_publish("work-submit"),
        ),
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            get=lambda task_id: task if task_id == "task-1" else None,
            checkpoint=failed_checkpoint,
        ),
        services=SimpleNamespace(command=lambda *_args, **_kwargs: failed_publish("command")),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-1"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: dict(payload))
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, data: dict[str, Any]) -> None:
        if not getattr(self, "_journal_finished", False):
            success = http_server._journal_outcome_success(status, data)
            journal.finish("req-1", success, status_code=status, response=data)
            self._journal_finished = True
        responses.append((status, data))

    monkeypatch.setattr(http_server.Handler, "_send", respond)

    for _ in range(2):
        handler = object.__new__(http_server.Handler)
        handler.path = path
        handler.headers = {"Content-Type": "application/json"}
        http_server.Handler.do_POST(handler)

    assert calls == [expected_call], responses
    assert len(responses) == 2
    assert responses[1] == responses[0]


def test_bundle_import_retry_uses_content_and_target_fingerprint(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    bundle = b"fixed test bundle bytes"
    imports: list[tuple[bytes, str | None]] = []
    app = SimpleNamespace(
        config={"bundles": {"max_bundle_bytes": 1024}},
        recovery=journal,
        import_bundle=lambda raw, target: imports.append((raw, target)) or {"success": True, "imported": True},
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-bundle"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_body", lambda self, *, limit: bundle)
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, data: dict[str, Any]) -> None:
        if not getattr(self, "_journal_finished", False):
            journal.finish("req-bundle", http_server._journal_outcome_success(status, data), status_code=status, response=data)
            self._journal_finished = True
        responses.append((status, data))

    monkeypatch.setattr(http_server.Handler, "_send", respond)
    for _ in range(2):
        handler = object.__new__(http_server.Handler)
        handler.path = "/api/bundle/import?target_root=project"
        handler.headers = {"Content-Type": "application/zip"}
        http_server.Handler.do_POST(handler)

    assert imports == [(bundle, "project")]
    assert len(responses) == 2
    assert responses[1] == responses[0]


def test_bundle_import_failure_finishes_journal_and_is_not_replayed(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    calls: list[tuple[bytes, str | None]] = []

    def import_bundle(raw: bytes, target: str | None) -> dict[str, Any]:
        calls.append((raw, target))
        raise RuntimeError("private import detail")

    app = SimpleNamespace(
        config={"bundles": {"max_bundle_bytes": 1024}},
        recovery=journal,
        import_bundle=import_bundle,
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-bundle-failure"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_body", lambda self, *, limit: b"bundle")
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, data: dict[str, Any]) -> None:
        if not getattr(self, "_journal_finished", False):
            journal.finish(self._journal_request_id, http_server._journal_outcome_success(status, data), status_code=status, response=data)
            self._journal_finished = True
        responses.append((status, data))

    monkeypatch.setattr(http_server.Handler, "_send", respond)
    for _ in range(2):
        handler = object.__new__(http_server.Handler)
        handler.path = "/api/bundle/import?target_root=project"
        handler.headers = {"Content-Type": "application/zip"}
        http_server.Handler.do_POST(handler)

    assert len(calls) == 1
    assert [status for status, _data in responses] == [500, 500]
    assert "private import detail" not in str(responses)


def test_debug_trace_failure_after_claim_does_not_block_post_dispatch(monkeypatch, tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    submitted: list[dict[str, Any]] = []

    class BrokenTraceStore:
        def update(self, *_args: Any, **_kwargs: Any) -> None:
            raise OSError("trace store unavailable")

    app = SimpleNamespace(
        config={},
        recovery=journal,
        debug_traces=BrokenTraceStore(),
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda payload: submitted.append(dict(payload)) or {"success": True},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-trace-failure") or setattr(self, "_debug_trace_id", "trace-1"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: {"action": "submit", "work_id": "work-1"})
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []
    monkeypatch.setattr(http_server.Handler, "_send", lambda self, status, data: responses.append((status, data)))
    handler = object.__new__(http_server.Handler)
    handler.path = "/api/work-orders"
    handler.headers = {"Content-Type": "application/json"}

    http_server.Handler.do_POST(handler)

    assert submitted == [{"action": "submit", "work_id": "work-1"}]
    assert responses[0][0] == 200
    assert journal.lookup(
        "req-trace-failure", action="/api/work-orders",payload_fingerprint=journal.fingerprint_payload({"action": "submit", "work_id": "work-1"}),
    )["state"] == "running"


def test_tool_accounting_retry_does_not_duplicate_event_batch(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    events = [{"event_id": "event-1", "tool": "local_ai_repo"}]
    recorded: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={},
        recovery=journal,
        telemetry=SimpleNamespace(record_tool_accounting=lambda event: recorded.append(dict(event))),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-accounting"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: {"events": events})
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, data: dict[str, Any]) -> None:
        if not getattr(self, "_journal_finished", False):
            journal.finish("req-accounting", http_server._journal_outcome_success(status, data), status_code=status, response=data)
            self._journal_finished = True
        responses.append((status, data))

    monkeypatch.setattr(http_server.Handler, "_send", respond)
    for _ in range(2):
        handler = object.__new__(http_server.Handler)
        handler.path = "/api/telemetry/tool-accounting"
        handler.headers = {"Content-Type": "application/json"}
        http_server.Handler.do_POST(handler)

    assert recorded == events
    assert len(responses) == 2
    assert responses[1] == responses[0]


@pytest.mark.parametrize(
    ("path", "payload", "expected_call"),
    [
        ("/api/models/manage", {"action": "pull", "model": "test-model"}, "model-pull"),
        (
            "/api/agent-state/learning",
            {"action": "observe", "candidate_id": "candidate-1", "observation": {"latency_ms": 1}},
            "learning-blocked",
        ),
        ("/api/agent-state/cleanup", {"retention_days": 7}, "cleanup-blocked"),
        (
            "/api/agent-state/tasks",
            {"action": "cleanup_worktree", "task_id": "task-1"},
            "worktree-cleanup",
        ),
    ],
)
def test_http_request_journal_replays_action_mutations_once(
    tmp_path, monkeypatch, path: str, payload: dict[str, Any], expected_call: str
) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = dict(payload)
    task_root = str(tmp_path.resolve())
    session_id = "session-journal-replay"
    task = SimpleNamespace(context=SimpleNamespace(repository_id="", session_id=session_id))
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    if path == "/api/agent-state/tasks":
        payload["root"] = task_root
        from local_ai_hub.project_config import resolve_project_context

        task.context.repository_id = resolve_project_context(task_root, state_dir).coordination_id
        task.owner = "agent-a"
        task.checkpoint = SimpleNamespace(state_data={
            "_agent_task_scope": {"version": 2, "repo_root": task_root},
        })
    calls: list[str] = []
    responses: list[tuple[int, dict[str, Any]]] = []

    def effect(name: str, result: Any = None) -> Any:
        calls.append(name)
        return result if result is not None else {"success": True, "effect": name}

    app = SimpleNamespace(
        config={
            "agent_state": {"retention_days": 30},
            "security": {
                "allowed_roots": [task_root],
            },
        },
        recovery=journal,
        rag=SimpleNamespace(),
        agent_state=SimpleNamespace(
            enabled=True,
            db_path=str(state_dir / "agent_state.sqlite3"),
            cleanup=lambda **_kwargs: effect("agent-state-cleanup"),
        ),
        agent_tasks=SimpleNamespace(
            enabled=True,
            state_store=SimpleNamespace(enabled=True),
            get=lambda task_id: task if task_id == "task-1" else None,
            cleanup_worktree=lambda *_args, **_kwargs: effect("worktree-cleanup"),
        ),
        agent_learning=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            observe=lambda *_args, **_kwargs: calls.append("learning-observe") or None,
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-action-family"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: dict(payload))
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    monkeypatch.setattr(
        http_server.Handler,
        "_handle_models_action",
        lambda _self, action, _model: effect(f"model-{action}"),
    )

    def respond(self, status: int, data: dict[str, Any]) -> None:
        if getattr(self, "_journal_request_id", None) and not getattr(self, "_journal_finished", False):
            journal.finish(
                "req-action-family",
                http_server._journal_outcome_success(status, data),
                status_code=status,
                response=data,
            )
            self._journal_finished = True
        responses.append((status, data))

    monkeypatch.setattr(http_server.Handler, "_send", respond)

    for _ in range(2):
        handler = object.__new__(http_server.Handler)
        handler.path = path
        handler.headers = {"Content-Type": "application/json"}
        http_server.Handler.do_POST(handler)

    if path in {"/api/agent-state/learning", "/api/agent-state/cleanup"}:
        assert [status for status, _data in responses] == [403, 403]
        assert calls == []
        assert journal.lookup(
            "req-action-family", action=path,payload_fingerprint=journal.fingerprint_payload(payload),
        ) is None
        return

    assert calls == [expected_call]
    assert len(responses) == 2
    assert responses[1] == responses[0]


def test_journal_outcome_unknown_overrides_terminal() -> None:
    assert http_server._journal_outcome_success(409, {"terminal": True, "outcome_unknown": True}) is False


def test_live_client_does_not_journal_typed_unknown_command_as_success(tmp_path, monkeypatch) -> None:
    from http.client import HTTPConnection
    import logging

    journal = RecoveryJournal(tmp_path / "recovery")
    payload = {"command": "publish", "root": str(tmp_path)}
    uncertain = {
        "success": False,
        "outcome_unknown": True,
        "fail_closed": True,
        "retryable": False,
        "terminal": True,
        "cache_hit": False,
        "coalesced": False,
        "cache_invalidation_failed": True,
        "cache_invalidation_errors": ["cache delete reported failure"],
    }
    dispatches: list[dict[str, Any]] = []

    def command(value: dict[str, Any], *, request_cancel_event=None) -> dict[str, Any]:
        assert isinstance(request_cancel_event, threading.Event)
        dispatches.append(dict(value))
        return dict(uncertain)

    telemetry = SimpleNamespace(record_live=lambda **_kwargs: None, record_http=lambda **_kwargs: None)
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={"observability": {}, "security": {}},
            recovery=journal,
            telemetry=telemetry,
            logger=logging.getLogger("test.typed-unknown-command"),
            services=SimpleNamespace(command=command),
        ),
    )
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)

    server = http_server.ThreadingHTTPServer(("127.0.0.1", 0), http_server.Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address
    config = tmp_path / "client.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=" + str(port) + "\nstate_dir='" + (tmp_path / "client-state").as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    client.agent = "agent-a"

    try:
        first = client.post("/api/command", payload, timeout=5.0, request_id="t07-typed-unknown")
        retry = client.post("/api/command", payload, timeout=5.0, request_id="t07-typed-unknown")
        changed = client.post(
            "/api/command",
            {**payload, "command": "different publish"},
            timeout=5.0,
            request_id="t07-typed-unknown",
        )
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5.0)

    fingerprint = journal.fingerprint_payload(payload)
    stored = journal.lookup(
        "t07-typed-unknown", action="/api/command",payload_fingerprint=fingerprint,
    )
    assert first["success"] is False
    assert first["outcome_unknown"] is True
    assert first["request_id"] == "t07-typed-unknown"
    assert "verification_receipt" not in first
    assert retry == first
    assert changed.get("status_code") == 409
    assert dispatches == [payload]
    assert first.get("status_code") == 409 and stored["state"] == "failed", (
        f"typed unknown was returned as HTTP {first.get('status_code', 200)} "
        f"and journaled as {stored['state']} (status {stored['status_code']})"
    )
    assert stored["response"]["outcome_unknown"] is True

def test_http_retry_after_restart_is_unknown_and_never_redispatches(tmp_path, monkeypatch) -> None:
    import logging

    request_id = "t07-restart-outcome-unknown"
    payload = {
        "action": "submit",
        "root": str(tmp_path),
        "task": "restart idempotency contract",
        "work_id": "work-before-restart",
    }
    first_process = RecoveryJournal(tmp_path / "recovery")
    claim = first_process.begin(
        request_id, action="/api/work-orders",payload=payload,
    )
    assert claim["claimed"] is True

    restarted = RecoveryJournal(tmp_path / "recovery")
    dispatches: list[dict[str, Any]] = []
    telemetry = SimpleNamespace(record_live=lambda **_kwargs: None, record_http=lambda **_kwargs: None)
    monkeypatch.setattr(
        http_server,
        "APP",
        SimpleNamespace(
            config={"observability": {}, "security": {}},
            recovery=restarted,
            telemetry=telemetry,
            logger=logging.getLogger("test.restart-outcome-unknown"),
            work_orchestrator=SimpleNamespace(
                enabled=True,
                submit=lambda value: dispatches.append(dict(value)) or {"success": True},
            ),
        ),
    )
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)

    server = http_server.ThreadingHTTPServer(("127.0.0.1", 0), http_server.Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address
    config = tmp_path / "client.toml"
    config.write_text(
        "[server]\nbind='127.0.0.1'\nport=" + str(port) + "\nstate_dir='" + (tmp_path / "client-state").as_posix() + "'\n",
        encoding="utf-8",
    )
    client = HubClient(config_path=str(config), auto_start=False)
    client.agent = "agent-a"

    try:
        first = client.post("/api/work-orders", payload, timeout=5.0, request_id=request_id)
        repeated = client.post("/api/work-orders", payload, timeout=5.0, request_id=request_id)
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5.0)

    assert first["success"] is False
    assert first.get("outcome_unknown") is True, first
    assert first["retryable"] is False
    assert first["request_id"] == request_id
    assert repeated == first
    assert dispatches == []

def test_wait_observation_failure_is_unknown_without_rewriting_committed_outcome(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    request_id = "req-wait-observation-failure"
    payload = {"action": "submit", "root": str(tmp_path), "task": "observation failure contract"}
    original = journal.begin(request_id, action="/api/work-orders",payload=payload)
    assert original["claimed"] is True
    committed = {"success": True, "work_id": "committed-before-observation-error"}

    def finish_then_fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        journal.finish(request_id, True, status_code=200, response=committed)
        raise OSError("journal observation failed after durable completion")

    monkeypatch.setattr(journal, "wait_for", finish_then_fail)
    app = SimpleNamespace(config={"resilience": {"singleflight_wait_timeout_seconds": 0.05}}, recovery=journal)
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", request_id))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: dict(payload))
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    dispatched: list[dict[str, Any]] = []
    app.work_orchestrator = SimpleNamespace(
        enabled=True,
        submit=lambda value: dispatched.append(dict(value)) or {"success": True},
    )
    responses: list[tuple[int, dict[str, Any]]] = []
    monkeypatch.setattr(http_server.Handler, "_send", lambda self, status, data: responses.append((status, data)))

    handler = object.__new__(http_server.Handler)
    handler.path = "/api/work-orders"
    handler.headers = {"Content-Type": "application/json", "X-LocalAI-Request-ID": request_id}
    http_server.Handler.do_POST(handler)

    stored = journal.lookup(
        request_id, action="/api/work-orders",payload_fingerprint=journal.fingerprint_payload(payload),
    )
    assert dispatched == []
    assert responses[0][0] == 409
    assert responses[0][1]["outcome_unknown"] is True
    assert responses[0][1]["retryable"] is False
    assert responses[0][1]["request_id"] == request_id
    assert stored["state"] == "done"
    assert stored["status_code"] == 200
    assert stored["response"] == committed

@pytest.mark.parametrize(
    ("headers", "expected_request_id"),
    [({"X-LocalAI-Request-ID": "caller-request-1"}, "caller-request-1"), ({}, None)],
)
def test_async_delivery_uses_only_caller_request_id(monkeypatch, headers, expected_request_id) -> None:
    submitted: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={},
        telemetry=SimpleNamespace(http_latency_estimate=lambda _path: {"samples": 5}),
        async_jobs=SimpleNamespace(
            submit=lambda _action, payload: submitted.append(dict(payload)) or {"job_id": "job-1"}
        ),
        debug_traces=None,
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server, "decide_delivery", lambda *_args, **_kwargs: {"mode": "async"})
    handler = object.__new__(http_server.Handler)
    handler.headers = headers
    handler._trace_request_id = "server-generated-trace-id"

    status, _result = http_server.Handler._async_delivery(
        handler, "/api/reason", {"delivery": "async", "task": "bounded task"}
    )

    assert status == 200
    assert len(submitted) == 1
    assert submitted[0].get("request_id") == expected_request_id

def test_direct_async_submit_carries_caller_request_id(tmp_path, monkeypatch) -> None:
    from local_ai_hub.resilience import RecoveryJournal

    submitted: list[dict[str, Any]] = []
    app = SimpleNamespace(
        config={},
        recovery=RecoveryJournal(tmp_path),
        async_jobs=SimpleNamespace(
            submit=lambda _action, payload: submitted.append(dict(payload)) or {"success": True}
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(
        http_server.Handler,
        "_begin_trace",
        lambda self, _path: setattr(self, "_trace_request_id", "caller-request-2"),
    )
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda _self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda _self: "agent-a")
    monkeypatch.setattr(
        http_server.Handler,
        "_read_json",
        lambda _self: {"action": "submit", "job_action": "reason", "task": "bounded task"},
    )
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda _self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []

    def respond(self, status: int, body: dict[str, Any]) -> None:
        if not getattr(self, "_journal_finished", False):
            app.recovery.finish(self._journal_request_id, status < 400, status_code=status, response=body)
            self._journal_finished = True
        responses.append((status, body))

    monkeypatch.setattr(http_server.Handler, "_send", respond)

    def request() -> None:
        handler = object.__new__(http_server.Handler)
        handler.path = "/api/async-jobs"
        handler.headers = {"Content-Type": "application/json", "X-LocalAI-Request-ID": "caller-request-2"}
        http_server.Handler.do_POST(handler)

    request()
    request()

    assert [status for status, _body in responses] == [200, 200]
    assert responses[1][1] == responses[0][1]
    assert len(submitted) == 1
    assert submitted[0]["request_id"] == "caller-request-2"
