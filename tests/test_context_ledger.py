from __future__ import annotations

import asyncio
import hashlib

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub import mcp_server
import local_ai_hub.context_ledger as context_ledger_module
from local_ai_hub.context_ledger import ContextLedger
from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.token_accounting import json_tokens


def test_ledger_keeps_bounded_metadata_only_summary() -> None:
    ledger = ContextLedger(max_entries=2)
    ledger.record(
        tool="local_ai_repo",
        operation="search",
        request_tokens=100,
        response_tokens=40,
        saved_tokens=60,
        cache_outcome="miss",
        result_id="r1",
        session_id="session-a",
    )
    ledger.record(
        tool="local_ai_command",
        operation="run",
        request_tokens=80,
        response_tokens=20,
        saved_tokens=10,
        cache_outcome="hit",
        result_id="r2",
        session_id="session-a",
    )
    ledger.record(
        tool="local_ai_artifact",
        operation="slice",
        request_tokens=30,
        response_tokens=10,
        saved_tokens=5,
        cache_outcome="miss",
        result_id="r3",
        session_id="session-a",
    )

    snapshot = ledger.snapshot()
    assert snapshot["entries"] == 2
    assert snapshot["totals"]["request_tokens"] == 110
    assert snapshot["totals"]["response_tokens"] == 30
    assert snapshot["last"]["result_id"] == "r3"
    assert "session-a" not in str(snapshot["last"].get("prompt", ""))
    assert "source" not in str(snapshot).lower()


def test_ledger_adaptive_profile_drops_repeated_calls_to_minimal() -> None:
    ledger = ContextLedger(max_entries=8)
    for index in range(4):
        ledger.record(
            tool="local_ai_repo",
            operation="search",
            request_tokens=10,
            response_tokens=100,
            saved_tokens=20,
            cache_outcome="hit",
            result_id=f"r{index}",
        )
    assert ledger.adaptive_profile("compact") == "minimal"


def test_ledger_aggregates_accounting_breakdown_with_bounded_eviction() -> None:
    ledger = ContextLedger(max_entries=2)
    for request, protocol, schema, local in (
        (10, 20, 30, 40),
        (1, 2, 3, 4),
        (7, 8, 9, 10),
    ):
        ledger.record(
            tool="local_ai_repo",
            operation="context",
            request_tokens=request,
            response_tokens=1,
            protocol_tokens_est=protocol,
            schema_tokens_est=schema,
            local_compute_reused_tokens_est=local,
        )

    totals = ledger.snapshot()["totals"]
    assert totals["protocol_tokens_est"] == 10
    assert totals["schema_tokens_est"] == 12
    assert totals["local_compute_reused_tokens_est"] == 14


def test_ledger_recomputes_signed_savings_only_from_current_baseline(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "state")
    evidence_id = store.put(
        str(root),
        {
            "path": "source.py",
            "file_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "start_line": 1,
            "end_line": 1,
            "text": "value = 1",
        },
    )
    assert evidence_id is not None
    ledger = ContextLedger()

    ledger.record(
        tool="local_ai_repo",
        operation="context",
        response_tokens=50,
        saved_tokens=999,
        baseline_tokens_est=20,
        baseline_evidence_id=evidence_id,
        evidence_store=store,
        protocol_tokens_est=7,
        schema_tokens_est=5,
        local_compute_reused_tokens_est=3,
    )
    source.write_text("value = 2\n", encoding="utf-8")
    ledger.record(
        tool="local_ai_repo",
        operation="context",
        response_tokens=1,
        saved_tokens=1000,
        baseline_tokens_est=2000,
        baseline_evidence_id=evidence_id,
        evidence_store=store,
    )
    ledger.record(
        tool="local_ai_repo",
        operation="context",
        response_tokens=1,
        baseline_tokens_est=2000,
        baseline_evidence_id="EFFFFFFFFFFFFFFFFFFFF",
        evidence_store=store,
    )

    snapshot = ledger.snapshot()
    assert snapshot["totals"]["saved_tokens"] == -30
    assert snapshot["totals"]["protocol_tokens_est"] == 7
    assert snapshot["totals"]["schema_tokens_est"] == 5
    assert snapshot["totals"]["local_compute_reused_tokens_est"] == 3
    assert snapshot["last"]["saved_tokens"] == 0
    assert snapshot["last"]["baseline_evidence_id"] == ""
    assert snapshot["entries"] == 3


def test_project_context_changes_ledger_reuse_key() -> None:
    ledger = ContextLedger()
    common = {
        "task_id": "task-7",
        "revision": "rev-7",
        "evidence_ids": ("evidence-7",),
        "context": "same context",
        "root": "C:/repo",
        "session_id": "session-7",
        "phase": "search",
        "preload_profile": "review",
    }
    project_a = ledger.compile(
        **common,
        path_hints=({"path": "docs/a.md", "provenance": "project_config:pinned_context"},),
        settings_digest="a" * 32,
    )
    identical = ledger.compile(
        **common,
        path_hints=({"path": "docs/a.md", "provenance": "project_config:pinned_context"},),
        settings_digest="a" * 32,
    )
    changed_digest = ledger.compile(
        **common,
        path_hints=({"path": "docs/a.md", "provenance": "project_config:pinned_context"},),
        settings_digest="b" * 32,
    )
    changed_hint = ledger.compile(
        **common,
        path_hints=({"path": "docs/b.md", "provenance": "project_config:pinned_context"},),
        settings_digest="a" * 32,
    )

    assert identical["reuse_key"] == project_a["reuse_key"]
    assert changed_digest["reuse_key"] != project_a["reuse_key"]
    assert changed_hint["reuse_key"] != project_a["reuse_key"]


def test_materialized_context_pointer_is_scope_bound_and_ttl_limited(tmp_path, monkeypatch) -> None:
    now = [1_000.0]
    monkeypatch.setattr(context_ledger_module.time, "time", lambda: now[0])
    artifact_store = ArtifactStore(tmp_path / "state")
    ledger = ContextLedger(pointer_ttl_seconds=3)
    root = tmp_path / "repo"
    root.mkdir()
    compile_values = {
        "task_id": "task-1",
        "revision": "rev-1",
        "evidence_ids": ["E123"],
        "context": "current context",
        "root": str(root),
        "session_id": "session-1",
        "settings_digest": "config-a",
        "artifact_store": artifact_store,
    }

    first = ledger.compile(**compile_values)
    materialized = ledger.materialize(
        first["reuse_key"], artifact_store,
        root=str(root), task_id="task-1", session_id="session-1",
    )
    assert materialized["success"] is True
    assert materialized["text"] == "current context"

    assert ledger.materialize(
        first["reuse_key"], artifact_store,
        root=str(root), task_id="task-1", session_id="session-2",
    )["success"] is False
    assert ledger.materialize(
        first["reuse_key"], artifact_store,
        root=str(root / "other"), task_id="task-1", session_id="session-1",
    )["success"] is False

    second = ledger.compile(**(compile_values | {"settings_digest": "config-b"}))
    assert second["reuse_key"] != first["reuse_key"]
    assert ledger.materialize(
        first["reuse_key"], artifact_store,
        root=str(root), task_id="task-1", session_id="session-1",
    )["success"] is False
    assert ledger.materialize(
        second["reuse_key"], artifact_store,
        root=str(root), task_id="task-1", session_id="session-1",
    )["success"] is True

    now[0] += 4
    expired = ledger.materialize(
        second["reuse_key"], artifact_store,
        root=str(root), task_id="task-1", session_id="session-1",
    )
    assert expired["success"] is False
    assert expired["status"] == "stale"


def test_registered_context_dispatch_records_bounded_accounting(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    ledger = ContextLedger()
    monkeypatch.setattr(mcp_server, "CONTEXT_LEDGER", ledger)
    events = []
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda event: events.append(dict(event)))
    client = mcp_server.HubClient(auto_start=False)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    calls = []
    response = {
        "success": True,
        "adaptive_context_pack": {
            "context_id": "ctx-budget-accounting",
            "evidence": [{
                "evidence_id": "E12345678901234567890",
                "path": "source.py",
                "start_line": 1,
                "end_line": 1,
                "source": "deterministic",
            }],
            "context": "x" * 5000,
        },
    }

    def post(path, payload, timeout=None):
        calls.append((path, payload, timeout))
        return response

    monkeypatch.setattr(client, "post", post)
    result = asyncio.run(mcp_server.mcp.call_tool(
        "local_ai_repo",
        {"action": "context", "root": str(root), "query": "budget accounting", "mode": "adaptive", "max_response_tokens": 1024},
    ))

    assert calls[0][0] == "/api/context/pack"
    assert len(events) == 1
    assert isinstance(result, tuple)
    projected = result[1]
    returned_tokens = projected["response_budget"]["returned_tokens"]
    assert returned_tokens <= 1024
    assert json_tokens(projected) <= 1024
    assert result[0][0].text
    accounting = ledger.snapshot()["last"]
    assert accounting["tool"] == "local_ai_repo"
    assert accounting["operation"] == "context"
    assert accounting["request_tokens"] > 0
    assert accounting["response_tokens"] == events[0]["agent_tool_response_tokens_est"] > 0
    assert len(events) == 1
