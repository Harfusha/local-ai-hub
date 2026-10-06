from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import threading
from types import SimpleNamespace
from typing import Any

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


def test_repair_loop_does_not_replay_failed_mutating_command(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
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
        "tenant",
        max_attempts=2,
        fix_generator=generate,
    )

    assert result["success"] is False
    assert result["repair_skipped"] is True
    assert result["outcome_unknown"] is True
    assert executions == ["git add changed.py"]
    assert generator_calls == []


def test_repair_loop_stops_after_timed_out_command_outcome_is_unknown(tmp_path, monkeypatch) -> None:
    broker = _broker(tmp_path)
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
        "tenant",
        max_attempts=3,
        fix_generator=generate,
    )

    assert result["success"] is False
    assert result["outcome_unknown"] is True
    assert result["attempts"] == 0
    assert executions == [command]
    assert generator_calls == []


def test_recovery_journal_replays_the_same_payload_after_response_loss(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"action": "checkpoint", "task_id": "task-1", "state": "done"}

    first = journal.begin("req-1", "tenant", "/api/tasks/checkpoint", identity="agent-a", payload=payload)
    journal.finish("req-1", True, status_code=200, response={"success": True, "checkpoint_id": "cp-1"})
    retry = journal.begin("req-1", "tenant", "/api/tasks/checkpoint", identity="agent-a", payload=payload)

    assert first["claimed"] is True
    assert retry["claimed"] is False
    assert retry["state"] == "done"
    assert retry["response"] == {"success": True, "checkpoint_id": "cp-1"}


def test_begin_requires_identity_and_payload(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)

    with pytest.raises(TypeError):
        journal.begin("req-required", "tenant", "/api/work-orders", payload={"action": "submit"})
    with pytest.raises(TypeError):
        journal.begin("req-required", "tenant", "/api/work-orders", identity="agent-a")


def test_recovery_journal_conflicts_when_request_payload_changes(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    journal.begin("req-1", "tenant", "/api/tasks/checkpoint", identity="agent-a", payload={"state": "done"})

    retry = journal.begin("req-1", "tenant", "/api/tasks/checkpoint", identity="agent-a", payload={"state": "failed"})

    assert retry["claimed"] is False
    assert retry["state"] == "conflict"


@pytest.mark.parametrize(
    "request_id",
    ["", " req-1", "req 1", "req\r\nInjected: yes", "\x7f", "r" * 129, "réq-1", None, 17],
)
def test_recovery_journal_rejects_invalid_request_ids_before_claim(tmp_path, request_id) -> None:
    journal = RecoveryJournal(tmp_path)

    with pytest.raises(ValueError, match="request_id"):
        journal.begin(request_id, "tenant", "/api/tasks/checkpoint", identity="agent-a", payload={"state": "done"})

    with closing(sqlite3.connect(journal.path)) as con:
        count = con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    assert count == 0


def test_wait_for_preserves_unknown_after_process_interruption(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    journal.begin("req-1", "tenant", "/api/work-orders", identity="agent-a", payload={"action": "submit"})
    journal.mark_interrupted_on_startup()

    result = journal.wait_for(
        "req-1", "tenant", "/api/work-orders", identity="agent-a",
        payload_fingerprint=journal.fingerprint_payload({"action": "submit"}), timeout_seconds=0.01,
    )

    assert result is not None
    assert result["state"] == "abandoned"
    assert result["outcome_unknown"] is True


def test_lookup_requires_identity_and_payload_fingerprint(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"action": "submit"}
    journal.begin("req-identity", "tenant", "/api/work-orders", identity="agent-a", payload=payload)
    journal.finish("req-identity", True, response={"secret": "stored"})
    fingerprint = journal.fingerprint_payload(payload)

    with pytest.raises(TypeError):
        journal.lookup("req-identity", "tenant", "/api/work-orders", payload_fingerprint=fingerprint)
    with pytest.raises(TypeError):
        journal.lookup("req-identity", "tenant", "/api/work-orders", identity="agent-a")

    assert journal.lookup(
        "req-identity", "tenant", "/api/work-orders", identity="agent-b", payload_fingerprint=fingerprint
    )["state"] == "conflict"
    assert journal.lookup(
        "req-identity", "tenant", "/api/work-orders", identity="agent-a", payload_fingerprint="different"
    )["state"] == "conflict"


def test_wait_for_requires_identity_and_payload_fingerprint(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"action": "submit"}
    journal.begin("req-wait-identity", "tenant", "/api/work-orders", identity="agent-a", payload=payload)
    fingerprint = journal.fingerprint_payload(payload)

    with pytest.raises(TypeError):
        journal.wait_for("req-wait-identity", "tenant", "/api/work-orders", timeout_seconds=0, payload_fingerprint=fingerprint)
    with pytest.raises(TypeError):
        journal.wait_for("req-wait-identity", "tenant", "/api/work-orders", timeout_seconds=0, identity="agent-a")

    journal.finish("req-wait-identity", True, response={"secret": "stored"})
    identity_mismatch = journal.wait_for(
        "req-wait-identity", "tenant", "/api/work-orders", timeout_seconds=0,
        identity="agent-b", payload_fingerprint=fingerprint,
    )
    payload_mismatch = journal.wait_for(
        "req-wait-identity", "tenant", "/api/work-orders", timeout_seconds=0,
        identity="agent-a", payload_fingerprint="different",
    )
    assert identity_mismatch == {"state": "conflict"}
    assert payload_mismatch == {"state": "conflict"}


def test_trusted_lookup_metadata_never_returns_stored_response(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"action": "submit"}
    journal.begin("req-trace-metadata", "tenant", "/api/work-orders", identity="agent-a", payload=payload)
    journal.finish("req-trace-metadata", True, response={"secret": "stored"})

    metadata = journal.lookup_metadata(
        "req-trace-metadata", "tenant", "/api/work-orders", identity="agent-a"
    )

    assert metadata["state"] == "done"
    assert "response" not in metadata


@pytest.mark.parametrize(
    ("tenant", "identity", "action"),
    [
        ("other-tenant", "agent-a", "/api/tasks/checkpoint"),
        ("tenant", "agent-b", "/api/tasks/checkpoint"),
        ("tenant", "agent-a", "/api/tasks/cleanup"),
    ],
)
def test_recovery_journal_binds_id_to_tenant_identity_and_operation(tmp_path, tenant: str, identity: str, action: str) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"state": "done"}
    journal.begin("req-1", "tenant", "/api/tasks/checkpoint", identity="agent-a", payload=payload)

    retry = journal.begin("req-1", tenant, action, identity=identity, payload=payload)

    assert retry["claimed"] is False
    assert retry["state"] == "conflict"


def test_recovery_journal_claim_is_atomic_across_clients(tmp_path) -> None:
    journals = [RecoveryJournal(tmp_path), RecoveryJournal(tmp_path)]
    payload = {"document_id": "doc-1", "content": "stable"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda journal: journal.begin(
                "req-1", "tenant", "/api/rag/ingest_document", identity="agent-a", payload=payload
            ),
            journals,
        ))

    assert sum(bool(result["claimed"]) for result in results) == 1
    assert {result["state"] for result in results} == {"running"}


def test_recovery_journal_process_crash_stays_explicitly_unknown(tmp_path) -> None:
    journal = RecoveryJournal(tmp_path)
    journal.begin("req-1", "tenant", "/api/work-orders", identity="agent-a", payload={"action": "submit"})

    restarted = RecoveryJournal(tmp_path)
    retry = restarted.begin("req-1", "tenant", "/api/work-orders", identity="agent-a", payload={"action": "submit"})

    assert retry["claimed"] is False
    assert retry["state"] == "abandoned"
    assert retry["outcome_unknown"] is True


def test_corrupt_journal_rebuild_never_claims_mutations(tmp_path) -> None:
    (tmp_path / "recovery.sqlite3").write_bytes(b"not a sqlite database")

    first_process = RecoveryJournal(tmp_path)
    assert (tmp_path / "recovery.unavailable").exists()
    with pytest.raises(sqlite3.DatabaseError, match="refusing mutation dispatch"):
        first_process.begin("req-1", "tenant", "/api/command", identity="agent-a", payload={"command": "deploy"})

    restarted_process = RecoveryJournal(tmp_path)
    with pytest.raises(sqlite3.DatabaseError, match="refusing mutation dispatch"):
        restarted_process.begin("req-1", "tenant", "/api/command", identity="agent-a", payload={"command": "deploy"})


def test_response_is_journaled_before_a_client_disconnect(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    payload = {"action": "submit", "work_id": "work-1"}
    journal.begin("req-1", "tenant", "/api/work-orders", identity="agent-a", payload=payload)

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
        "req-1",
        "tenant",
        "/api/work-orders",
        identity="agent-a",
        payload_fingerprint=journal.fingerprint_payload(payload),
    )
    assert replay is not None
    assert replay["state"] == "done"
    assert replay["response"] == {"success": True, "work_id": "work-1"}


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
    calls: list[str] = []
    claimed = journal.begin("req-1", "tenant", path, identity="agent-a", payload=payload)
    assert claimed["claimed"] is True

    calls.append("publish began; later stage failed")
    failure = {"success": False, "error": "publish interrupted", "partial_publish": True}
    journal.finish("req-1", False, status_code=500, response=failure)
    retry = journal.begin("req-1", "tenant", path, identity="agent-a", payload=payload)

    assert calls == ["publish began; later stage failed"]
    assert retry["claimed"] is False
    assert retry["state"] == "failed"
    assert retry["response"] == failure


def test_rag_index_publish_failure_keeps_previous_snapshot(tmp_path) -> None:
    class _EmbeddingServices:
        def embed(self, texts, _tenant, **_kwargs):
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
    first = store.index(str(root), "tenant")
    assert first["success"] is True
    workspace = store.workspace_id(str(root))
    with closing(store._connect()) as con:
        old_file_hash = con.execute(
            "SELECT content_hash FROM files WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "one.py"),
        ).fetchone()[0]

    with closing(store._connect()) as con:
        con.execute(
            "CREATE TRIGGER fail_rag_publish BEFORE INSERT ON chunks "
            "WHEN NEW.path='one.py' BEGIN SELECT RAISE(ABORT, 'injected publish failure'); END"
        )
        con.commit()
    source.write_text("def value():\n    return 'new snapshot'\n", encoding="utf-8")

    try:
        second = store.index(str(root), "tenant", workspace=workspace)
    except sqlite3.DatabaseError:
        second = {"success": False}

    assert second["success"] is False
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT text FROM chunks WHERE tenant=? AND workspace=?",
            (store._scope_key("tenant"), workspace),
        ).fetchall()
        file_hash = con.execute(
            "SELECT content_hash FROM files WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "one.py"),
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
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config={}, services=services))
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
            submit=lambda _tenant, payload: submitted.append(payload) or {"success": True},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-1"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda self: "tenant")
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
            submit=lambda _tenant, payload: submitted.append(dict(payload)) or {"success": True, "work_id": payload["work_id"]},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-1"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda self: "tenant")
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
        "req-1",
        "tenant",
        "/api/work-orders",
        identity="agent-a",
        payload_fingerprint=journal.fingerprint_payload(original_payload),
    )
    changed = journal.lookup(
        "req-1",
        "tenant",
        "/api/work-orders",
        identity="agent-a",
        payload_fingerprint=journal.fingerprint_payload(payload_box["value"]),
    )
    assert original["response"] == responses[0][1]
    assert changed == {"state": "conflict", "error": "request id already belongs to a different identity, operation, or payload"}


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
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda self: "tenant")
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
        "req-publish-1",
        "tenant",
        "/api/coord/pubsub_publish",
        identity="agent-a",
        payload_fingerprint=journal.fingerprint_payload(original_payload),
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
            submit=lambda _tenant, payload: submitted.append(payload) or {"success": True},
        ),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda self: "tenant")
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
    }
    assert finished[0]["success"] is False
    assert finished[0]["status_code"] == 503
    assert finished[0]["response"] == expected
    assert json.loads(handler.wfile.getvalue().decode("utf-8")) == expected


@pytest.mark.parametrize(
    ("path", "payload", "expected_call"),
    [
        ("/api/rag/index", {"root": "project"}, "rag-index"),
        ("/api/rag/ingest_document", {"workspace": "default", "content": "doc"}, "rag-ingest"),
        ("/api/work-orders", {"action": "submit", "work_id": "work-1"}, "work-submit"),
        ("/api/agent-state/tasks", {"action": "checkpoint", "task_id": "task-1", "phase": "testing", "next_action": "verify"}, "task-checkpoint"),
        ("/api/command", {"command": "pytest"}, "command"),
    ],
)
def test_http_partial_publish_failure_replays_without_dispatching_twice(
    tmp_path, monkeypatch, path: str, payload: dict[str, Any], expected_call: str
) -> None:
    journal = RecoveryJournal(tmp_path)
    calls: list[str] = []

    def failed_publish(label: str) -> dict[str, Any]:
        calls.append(label)
        return {"success": False, "error": "partial publish", "partial_publish": True}

    def failed_checkpoint(*_args: Any, **_kwargs: Any) -> Any:
        calls.append("task-checkpoint")
        raise KeyError("checkpoint failed after partial publish")

    app = SimpleNamespace(
        config={},
        recovery=journal,
        async_jobs=SimpleNamespace(inference_admission=lambda _action: nullcontext()),
        rag=SimpleNamespace(
            index=lambda *_args, **_kwargs: failed_publish("rag-index"),
            ingest_document=lambda *_args, **_kwargs: failed_publish("rag-ingest"),
        ),
        work_orchestrator=SimpleNamespace(
            enabled=True,
            submit=lambda *_args, **_kwargs: failed_publish("work-submit"),
        ),
        agent_tasks=SimpleNamespace(
            state_store=SimpleNamespace(enabled=True),
            checkpoint=failed_checkpoint,
        ),
        services=SimpleNamespace(command=lambda *_args, **_kwargs: failed_publish("command")),
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(http_server.Handler, "_begin_trace", lambda self, _path: setattr(self, "_trace_request_id", "req-1"))
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda self: "tenant")
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

    assert calls == [expected_call]
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
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda self: "tenant")
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
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda self: "tenant")
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


def test_confirmed_restart_request_is_not_replayed(tmp_path, monkeypatch) -> None:
    journal = RecoveryJournal(tmp_path)
    app = SimpleNamespace(
        config={
            "server": {"state_dir": str(tmp_path)},
            "resilience": {"singleflight_wait_timeout_seconds": 0.05},
        },
        recovery=journal,
        close=lambda: None,
    )
    monkeypatch.setattr(http_server, "APP", app)
    monkeypatch.setattr(
        http_server.Handler,
        "_begin_trace",
        lambda self, _path: setattr(self, "_trace_request_id", "req-restart-once"),
    )
    monkeypatch.setattr(http_server.Handler, "_require_authorized", lambda self: True)
    monkeypatch.setattr(http_server.Handler, "_agent", lambda self: "agent-a")
    monkeypatch.setattr(http_server.Handler, "_tenant", lambda self: "tenant")
    monkeypatch.setattr(http_server.Handler, "_read_json", lambda self: {"action": "restart_hub"})
    monkeypatch.setattr(http_server.Handler, "_validate_payload", lambda self, _path, _payload: None)
    responses: list[tuple[int, dict[str, Any]]] = []
    scheduled: list[Any] = []

    def respond(self, status: int, data: dict[str, Any]) -> None:
        responses.append((status, data))

    class DeferredThread:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            scheduled.append((args, kwargs))

        def start(self) -> None:
            pass

    monkeypatch.setattr(http_server.Handler, "_send", respond)
    monkeypatch.setattr(http_server.threading, "Thread", DeferredThread)
    for _ in range(2):
        handler = object.__new__(http_server.Handler)
        handler.path = "/api/control"
        handler.headers = {"Content-Type": "application/json"}
        http_server.Handler.do_POST(handler)

    assert len(scheduled) == 1
    assert responses[0][0] == 200
    assert responses[1][0] == 409
    assert responses[1][1]["in_progress"] is True
    assert journal.lookup(
        "req-restart-once",
        "tenant",
        "/api/control",
        identity="agent-a",
        payload_fingerprint=journal.fingerprint_payload({"action": "restart_hub"}),
    )["state"] == "running"
