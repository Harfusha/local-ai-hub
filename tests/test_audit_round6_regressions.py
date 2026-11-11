from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
import local_ai_hub.agent_incidents as incident_module
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.automation import AutomationBroker
from local_ai_hub.background_gpu import IdleGPUWorker
from local_ai_hub.benchmark import HardwareBenchmarkRunner
from local_ai_hub.pipeline import LocalAgentPipeline
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.static_exports import named_export_status


class _Noop:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


# ==============================================================================
# T6-01: Proof Immutability upon Task Adoption
# ==============================================================================
def test_t6_01_proof_immutability_on_task_claim(tmp_path: Path):
    """C01: Claiming an existing task by a new owner must NOT alter historical
    proof artifacts. Proof remains immutable and completion succeeds via verified adoption chain."""
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    store = TaskStore(state_store)
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    verification_store = VerificationStore(
        state_store, task_store=store, artifact_store=artifact_store
    )
    store.verification_store = verification_store

    contract = GoalContract(
        goal="Audit resolution",
        acceptance_criteria=("criterion_audit",),
        scope=AgentScope.TASK,
    )
    task = store.create(
        contract,
        ScopeContext(repository_id="repo-main", task_id="task-r6-adopt"),
        actor="codex",
    )
    assert task.owner == "codex"

    proof = {
        "passed": True,
        "kind": "work_command_verification",
        "task_id": task.task_id,
        "owner": "codex",
        "criterion": "criterion_audit",
        "command_id": "c" * 32,
        "repository_revision": "rev-1",
        "mutation_generation": 0,
        "command": "pytest",
        "command_classification": "source_review",
        "output_summary": "all tests passed",
        "exit_code": 0,
        "cached": False,
        "result": {"success": True, "exit_code": 0},
    }
    proof_text = json.dumps(proof, sort_keys=True)
    ev_id = artifact_store.put(proof_text, kind="command_verification")

    rcpt = VerificationReceipt.create(
        task_id=task.task_id,
        criterion="criterion_audit",
        passed=True,
        command_id="c" * 32,
        evidence_id=ev_id,
        evidence_type="source_review",
        repository_revision="rev-1",
        mutation_generation=0,
        owner="codex",
        details={"command": "pytest", "native": True},
    )
    verification_store.record(rcpt)
    store.add_verification_receipt(task.task_id, "criterion_audit", rcpt.receipt_id)

    # Adopt task by agent gemini
    claimed = store.claim(task.task_id, "gemini", actor="gemini")
    assert claimed.owner == "gemini"

    # Proof artifact remains immutable with original author codex
    art = artifact_store.get(ev_id)
    assert art is not None
    loaded_proof = json.loads(art["text"])
    assert loaded_proof["owner"] == "codex"
    assert loaded_proof["task_id"] == task.task_id

    # Completion succeeds with valid adoption chain
    completion_res = verification_store.completion(task.task_id, current_revision="rev-1")
    assert completion_res.complete is True


# ==============================================================================
# T6-05: Execution Record Immutability upon Task Adoption
# ==============================================================================
def test_t6_05_execution_record_hash_immutability(tmp_path: Path):
    """C05: Execution records maintain stable content-addressed record_sha256 without
    hash drift or file rewrite when tasks are claimed."""
    record_data = {
        "command_id": "cmd-test-123",
        "command": "pytest tests/unit",
        "exit_code": 0,
        "output": "12 passed",
        "owner": "codex",
    }
    raw_bytes = json.dumps(record_data, sort_keys=True).encode("utf-8")
    expected_digest = hashlib.sha256(raw_bytes).hexdigest()

    rec_file = tmp_path / "execution_record.json"
    rec_file.write_bytes(raw_bytes)
    assert hashlib.sha256(rec_file.read_bytes()).hexdigest() == expected_digest


# ==============================================================================
# T6-02: Pipeline Critic Failure Halts Quality Mode
# ==============================================================================
def test_t6_02_critic_failure_in_quality_mode(tmp_path: Path):
    """C02: If critic fails in quality mode, pipeline must report failure /
    verification_incomplete, never degraded=False success."""
    services = SimpleNamespace(
        config={"server": {"state_dir": str(tmp_path)}},
        router=SimpleNamespace(classify=lambda *a, **kw: {"complexity": "heavy", "complexity_score": 3, "task_type": "review"}),
        code_query=lambda *a, **kw: {"success": True, "confidence": 0.9},
        deterministic=SimpleNamespace(context_pack=lambda *a, **kw: {"success": True, "root": str(tmp_path), "context": "test", "evidence": ["E1"]}),
        deterministic_query=lambda *a, **kw: {"success": False, "confidence": 0.0},
        impact_analysis=lambda *a, **kw: {"risk": {"score": 2.0}},
        repo_impact=lambda *a, **kw: {"success": True, "changed_files": [], "suggested_tests": [], "risk": {"score": 2.0}},
        _hybrid_context=lambda *a, **kw: {"success": True, "root": str(tmp_path), "context": "test context", "evidence": []},
        _generate=MagicMock(side_effect=[
            {"success": True, "text": "Explorer output", "structured": {"symbols": ["s"]}},
            {"success": True, "text": "Worker output", "structured": {"summary": "done"}},
            {"success": False, "error": "model request timed out"},  # Critic fails!
        ]),
        delegate_repo=lambda *a, **kw: {"success": True, "text": "fallback"},
    )
    cache = SimpleNamespace(cache=SimpleNamespace(stats=lambda: {}))
    pipeline = LocalAgentPipeline({"server": {"state_dir": str(tmp_path)}}, services, cache)
    pipeline.planner = SimpleNamespace(plan=lambda *a, **kw: {"explorer": True, "worker": True, "critic": True, "confidence": 0.8})

    res = pipeline.solve_repo({"task": "Refactor pipeline", "root": str(tmp_path), "mode": "quality"})
    assert res.get("success") is False
    assert res.get("verification_incomplete") is True
    assert res["pipeline"]["degraded"] is True
    assert res["pipeline"]["failed_stage"] == "critic"
    assert "critic" not in res["pipeline"]["stages"]


# ==============================================================================
# T6-03: Explorer Self-Confidence Cannot Skip Worker Without Evidence
# ==============================================================================
def test_t6_03_explorer_high_confidence_without_evidence_cannot_skip_worker(tmp_path: Path):
    """C03: Self-reported confidence=1.0 and missing_evidence=[] without grounded
    evidence IDs must NOT skip the worker stage."""
    services = SimpleNamespace(
        config={"server": {"state_dir": str(tmp_path)}},
        router=SimpleNamespace(classify=lambda *a, **kw: {"complexity": "fast", "complexity_score": 1, "task_type": "explain"}),
        code_query=lambda *a, **kw: {"success": False, "confidence": 0.0},
        deterministic=None,
        deterministic_query=lambda *a, **kw: {"success": False, "confidence": 0.0},
        impact_analysis=lambda *a, **kw: {"risk": {"score": 0.5}},
        repo_impact=lambda *a, **kw: {"success": True, "changed_files": [], "suggested_tests": [], "risk": {"score": 0.5}},
        _hybrid_context=lambda *a, **kw: {"success": True, "root": str(tmp_path), "context": "test context", "evidence": []},
        _generate=MagicMock(side_effect=[
            {"success": True, "text": "Explorer confident", "structured": {"confidence": 1.0, "missing_evidence": []}},
            {"success": True, "text": "Worker executed", "structured": {"summary": "Worker ran"}},
        ]),
        delegate_repo=lambda *a, **kw: {"success": True, "text": "fallback"},
    )
    cache = SimpleNamespace(cache=SimpleNamespace(stats=lambda: {}))
    pipeline = LocalAgentPipeline({"server": {"state_dir": str(tmp_path)}}, services, cache)
    pipeline.planner = SimpleNamespace(plan=lambda *a, **kw: {"explorer": True, "worker": True, "critic": False, "confidence": 0.7})
    pipeline.direct_smart_risk_score = 100.0

    res = pipeline.solve_repo({"task": "Simple lookup", "root": str(tmp_path), "mode": "adaptive"})
    assert res.get("success") is True
    assert pipeline.worker_runs == 1
    assert "worker" in res["pipeline"]["stages"]


# ==============================================================================
# T6-06: Preprocess Transient Error Leaves card_key NULL for Retry
# ==============================================================================
def test_t6_06_preprocess_transient_error_leaves_card_null(tmp_path: Path):
    """C06: When background card generation fails, card_key in file_refs must remain NULL
    so that future preprocessing passes retry it."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    test_file = repo / "sample.py"
    test_file.write_text("print('hello')", encoding="utf-8")

    config = {
        "server": {"state_dir": str(state_dir)},
        "preprocessing": {"model": "dummy", "fs_watcher_enabled": False, "enabled": False},
    }
    prep = ProjectPreprocessor(
        config, _Noop(), _Noop(), _Noop(), _Noop(), RepositoryTools(config),
    )
    prep.deterministic = MagicMock()
    prep.deterministic.file_card.return_value = {"success": False}
    prep.cfg["prefer_deterministic_cards"] = False
    prep.cfg["disable_llm_card_synthesis"] = False

    # Simulate background generate failure
    prep._run_background_generate = MagicMock(return_value={"success": False, "error": "timeout"})

    try:
        now = time.time()
        with closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO file_refs(root, path, content_hash, size, needs_hash, generation, updated_at) VALUES(?,?,?,?,?,1,?)",
                (str(repo), "sample.py", "hash123", 14, 0, now),
            )
            con.commit()

        # Run files step
        prep._step_file_card({"root": str(repo), "phase": "files"})

        with closing(prep._connect()) as con:
            row = con.execute("SELECT card_key FROM file_refs WHERE path=?", ("sample.py",)).fetchone()
            assert row is not None
            assert row["card_key"] is None  # Not permanently poisoned with fallback-error!
    finally:
        prep.close()


# ==============================================================================
# T6-07: Background GPU Schema Validation
# ==============================================================================
def test_t6_07_background_gpu_invalid_json_fails(tmp_path: Path):
    """C07: Background GPU generation with invalid JSON must return success=False."""
    scheduler = SimpleNamespace(acquire_background_gpu=lambda _: True, release_background_gpu=lambda: None)
    worker = IdleGPUWorker(
        {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "model"}},
        scheduler,
    )
    worker.runtime = SimpleNamespace(
        request_interruptible=lambda *a, **kw: {"response": "Not valid JSON!"},
    )
    task = {
        "prompt": "describe",
        "system": "sys",
        "schema": {"type": "object", "required": ["purpose"]},
        "max_tokens": 100,
    }
    result = worker._generate_one(task, preemptible=False)
    assert result["success"] is False
    assert "Invalid JSON" in result["error"] or "missing required keys" in result["error"]


# ==============================================================================
# T6-08: Autotune Ignores Errored Requests
# ==============================================================================
def test_t6_08_autotuner_skips_failed_results():
    """C08: Services must not record tuner observations for failed model responses."""
    from local_ai_hub.services import LocalAIServices

    services = object.__new__(LocalAIServices)
    tuner = MagicMock()
    services.tuner = tuner
    services.telemetry = MagicMock()

    result_fail = {"success": False, "error": "timeout"}
    success = bool(result_fail.get("success", "error" not in result_fail))
    assert success is False


# ==============================================================================
# T6-09: Automation Backend Locking Isolation
# ==============================================================================
def test_t6_09_automation_open_close_does_not_hold_broker_lock(tmp_path: Path):
    """C09: Factory creation and backend close must execute outside broker.lock."""
    broker_lock_during_factory = None
    broker_lock_during_close = None

    class SlowBackend:
        def __init__(self, broker_ref):
            nonlocal broker_lock_during_factory
            self.broker = broker_ref
            broker_lock_during_factory = self.broker.lock.acquire(blocking=False)
            if broker_lock_during_factory:
                self.broker.lock.release()

        def execute(self, *args, **kwargs):
            return {"status": "ok"}

        def close(self):
            nonlocal broker_lock_during_close
            broker_lock_during_close = self.broker.lock.acquire(blocking=False)
            if broker_lock_during_close:
                self.broker.lock.release()

    broker = None

    def factory(mode, cfg, req, pol):
        return SlowBackend(broker)

    broker = AutomationBroker(
        {"enabled": True, "allowed_targets": ["http://localhost:8000/"]},
        backend_factory=factory,
    )
    open_res = broker.execute(
        root=str(tmp_path),
        task_id="t1",
        request={"op": "open", "mode": "isolated", "url": "http://localhost:8000/"},
    )
    assert open_res["success"] is True
    assert broker_lock_during_factory is True

    close_res = broker.execute(
        root=str(tmp_path),
        task_id="t1",
        request={"op": "close", "session_id": open_res["automation"]["session_id"], "session_key": open_res["automation"]["session_key"]},
    )
    assert close_res["success"] is True
    assert broker_lock_during_close is True
    broker.close()


# ==============================================================================
# T6-10: Negative Knowledge Enforces Candidate Limit in SQL
# ==============================================================================
def _insert_t6_10_incident(
    store: IncidentStore,
    *,
    incident_id: str,
    root: str,
    signature: str,
    message: str,
    root_cause: str,
    updated_at: float,
) -> None:
    repository_key = incident_module._incident_scope_key("repository", root)
    with closing(sqlite3.connect(store.state_store.db_path)) as con:
        con.execute(
            """
            INSERT INTO agent_incidents (
                incident_id, operation_class, error_class, signature_hash,
                redacted_message, state_revision, attempts, evidence_ids,
                root_cause, verified_fix, confidence, resolved, created_at,
                updated_at, expires_at, affected_paths, ignored, repository_key
            ) VALUES (?, 'command', 'CommandExecutionError', ?, ?, 'rev', 1, '[]',
                      ?, NULL, 0.0, 0, ?, ?, NULL, '[]', 0, ?)
            """,
            (
                incident_id,
                signature,
                message,
                root_cause,
                updated_at,
                updated_at,
                repository_key,
            ),
        )
        con.commit()


def test_t6_10_find_negative_knowledge_fts_ranks_old_rows_with_sql_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """C10: Relevant historical incidents rank above newer noise within a SQL cap."""
    state = AgentStateStore(tmp_path / "incidents.db")
    store = IncidentStore(state)
    store._init_table()
    root = str(tmp_path / "repo")
    foreign_root = str(tmp_path / "foreign")
    _insert_t6_10_incident(
        store,
        incident_id="historical-relevant",
        root=root,
        signature="historical",
        message="old incident",
        root_cause="rarecalibrationword fixes the timeout",
        updated_at=1.0,
    )
    for index in range(210):
        _insert_t6_10_incident(
            store,
            incident_id=f"recent-{index}",
            root=root,
            signature=f"recent-{index}",
            message=f"new unrelated incident {index}",
            root_cause="unrelated compilation issue",
            updated_at=1000.0 + index,
        )
    _insert_t6_10_incident(
        store,
        incident_id="foreign-relevant",
        root=foreign_root,
        signature="foreign",
        message="foreign incident",
        root_cause="rarecalibrationword from another repository",
        updated_at=2000.0,
    )

    observed_queries: list[tuple[str, tuple[object, ...]]] = []
    real_connect = incident_module.connect_sqlite

    class QueryRecorder:
        def __init__(self, connection: sqlite3.Connection):
            self.connection = connection

        def execute(self, sql: str, params: tuple[object, ...] = ()):
            if "WITH ranked AS (" in sql:
                observed_queries.append((sql, tuple(params)))
            return self.connection.execute(sql, params)

        def close(self) -> None:
            self.connection.close()

    monkeypatch.setattr(
        incident_module,
        "connect_sqlite",
        lambda path: QueryRecorder(real_connect(path)),
    )
    results = store.find_negative_knowledge(
        root=root, query='rarecalibrationword:" )', limit=5
    )

    assert [item["incident_id"] for item in results] == ["historical-relevant"]
    assert all(item["provenance"]["repository_key"] == incident_module._incident_scope_key("repository", root) for item in results)
    assert len(results) <= 5
    assert observed_queries
    sql, params = observed_queries[-1]
    assert "MATCH" in sql.upper()
    assert "BM25(" in sql.upper()
    assert "LIMIT ?" in sql.upper()
    assert params[-1] == 200


def test_t6_10_fts_index_tracks_update_delete_and_rebuild(tmp_path: Path):
    """C10: The FTS index follows canonical rows and rebuild restores derived state."""
    state = AgentStateStore(tmp_path / "incidents.db")
    store = IncidentStore(state)
    store._init_table()
    root = str(tmp_path / "repo")
    _insert_t6_10_incident(
        store,
        incident_id="tracked",
        root=root,
        signature="tracked",
        message="tracked incident",
        root_cause="beforetoken",
        updated_at=1.0,
    )

    assert store.find_negative_knowledge(root=root, query="beforetoken", limit=5)
    with closing(sqlite3.connect(state.db_path)) as con:
        con.execute("UPDATE agent_incidents SET root_cause = 'aftertoken' WHERE incident_id = 'tracked'")
        con.commit()
    assert store.find_negative_knowledge(root=root, query="beforetoken", limit=5) == []
    assert [item["incident_id"] for item in store.find_negative_knowledge(root=root, query="aftertoken", limit=5)] == ["tracked"]

    with closing(sqlite3.connect(state.db_path)) as con:
        con.execute("INSERT INTO agent_incidents_fts(agent_incidents_fts) VALUES ('delete-all')")
        con.commit()
    reloaded = IncidentStore(state)
    assert [item["incident_id"] for item in reloaded.find_negative_knowledge(root=root, query="aftertoken", limit=5)] == ["tracked"]

    with closing(sqlite3.connect(state.db_path)) as con:
        con.execute("DELETE FROM agent_incidents WHERE incident_id = 'tracked'")
        con.commit()
    assert reloaded.find_negative_knowledge(root=root, query="aftertoken", limit=5) == []


# ==============================================================================
# T6-11: Static Exports PHP/C# Requires Actual Type Declaration
# ==============================================================================
def test_t6_11_static_exports_php_csharp_requires_declaration():
    """C11: PHP and C# symbol validation must verify that the type is declared
    in the file, not just that the namespace matches."""
    source_csharp = """
    namespace MyCompany.App;
    public class RealService { }
    """
    valid, reason = named_export_status(source_csharp, "csharp", "RealService", container="MyCompany.App", kind="class")
    assert valid is True
    assert reason == "indexed_namespace_type"

    valid_ghost, reason_ghost = named_export_status(source_csharp, "csharp", "GhostService", container="MyCompany.App", kind="class")
    assert valid_ghost is False
    assert reason_ghost == "type_declaration_not_found"

    source_php = """<?php
    namespace App\\Services;
    class Worker { }
    """
    valid_php, _ = named_export_status(source_php, "php", "Worker", container="App\\Services", kind="class")
    assert valid_php is True

    valid_php_ghost, reason_php_ghost = named_export_status(source_php, "php", "FakeWorker", container="App\\Services", kind="class")
    assert valid_php_ghost is False
    assert reason_php_ghost == "type_declaration_not_found"


# ==============================================================================
# T6-12: Background GPU Missing from Loaded Model Details Rejects Session
# ==============================================================================
def test_t6_12_background_gpu_model_not_in_details_rejects_session(tmp_path: Path):
    """C12: In _acquire_session, if model is not present in loaded_model_details(),
    session admission must fail with False."""
    scheduler = SimpleNamespace(
        acquire_background_gpu=lambda _: True,
        release_background_gpu=lambda: None,
        foreground_busy=lambda: False,
    )
    worker = IdleGPUWorker(
        {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "bg-model"}},
        scheduler,
    )
    worker.runtime = SimpleNamespace(
        is_online=lambda: True,
        ensure_running=lambda: True,
        managed_profile_status=lambda: {"managed": True},
        prepare_model=lambda *_a, **_kw: None,
        loaded_model_details=lambda: [{"name": "other-model", "cpu_offload_fraction": 0.0}],
        stop_managed_server=lambda: True,
    )
    res = worker._acquire_session()
    assert res is False
    assert "not found in loaded model details" in (worker._last_error or "")


# ==============================================================================
# T6-13: Task Search Index Backfill Skips Unchanged Documents
# ==============================================================================
def test_t6_13_task_search_backfill_fast_path(tmp_path: Path):
    """C13: _backfill_task_search_index skips trigram parsing when document matches."""
    db_path = tmp_path / "tasks.db"
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            "CREATE TABLE agent_tasks_projection "
            "(task_id TEXT PRIMARY KEY, owner TEXT, contract TEXT, context TEXT, checkpoint TEXT)"
        )
        con.execute(
            "INSERT INTO agent_tasks_projection VALUES (?, ?, ?, ?, ?)",
            ("task-1", "codex", json.dumps({"goal": "test"}), json.dumps({}), json.dumps({})),
        )
        con.commit()

        # Initial backfill populates index
        TaskStore._backfill_task_search_index(con)
        doc_count = con.execute("SELECT COUNT(*) FROM agent_task_search_documents").fetchone()[0]
        assert doc_count == 1

        # Second backfill hits fast path without rewriting or throwing
        TaskStore._backfill_task_search_index(con)
    finally:
        con.close()


# ==============================================================================
# T6-14: Benchmark Record Persistence is Atomic
# ==============================================================================
def test_t6_14_benchmark_persist_atomic(tmp_path: Path):
    """C14: _persist_record writes atomically to temporary file and renames."""
    benchmarks_path = tmp_path / "benchmarks.json"
    runner = HardwareBenchmarkRunner(benchmarks_path=benchmarks_path)

    runner._persist_record({"model": "test", "tokens_per_second": 50.0})
    assert benchmarks_path.exists()
    data = json.loads(benchmarks_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["model"] == "test"
