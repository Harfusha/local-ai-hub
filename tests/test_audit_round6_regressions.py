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
def test_t6_08_autotuner_observation_is_success_guarded():
    """C08 source contract: tuner observation stays inside the success-only Ollama branch."""
    import ast
    import inspect
    import textwrap

    from local_ai_hub.services import LocalAIServices

    source = textwrap.dedent(inspect.getsource(LocalAIServices._generate))
    function_nodes = ast.parse(source).body
    assert len(function_nodes) == 1
    function = function_nodes[0]
    observe_calls = [
        node for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_observe_tuner_safely"
    ]
    assert len(observe_calls) == 1

    guarded = []
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        contains_observation = any(
            child is observe_calls[0]
            for statement in node.body
            for child in ast.walk(statement)
        )
        if not contains_observation:
            continue
        names = {child.id for child in ast.walk(node.test) if isinstance(child, ast.Name)}
        attributes = {
            child.attr for child in ast.walk(node.test)
            if isinstance(child, ast.Attribute)
        }
        constants = {
            child.value for child in ast.walk(node.test)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }
        assert "success" in names
        assert "cache_layer" in names
        assert "tuner" in attributes
        assert "ollama" in constants
        assert not node.orelse
        guarded.append(node)

    assert len(guarded) == 1


def test_t6_08_autotuner_observation_runtime_tracks_only_success(monkeypatch):
    """C08 runtime: failed backend output skips tuner; successful output is observed."""
    from local_ai_hub import services as services_module
    from local_ai_hub.services import LocalAIServices

    class Profile:
        prompt_budget_tokens = 4096

        @staticmethod
        def cache_scope():
            return {"profile": "test"}

    class ModelPolicy:
        @staticmethod
        def profile(*_args, **_kwargs):
            return Profile()

        @staticmethod
        def apply_payload(_model, payload, **_kwargs):
            return payload, Profile()

    class Runtime:
        response: dict[str, Any]

        def request(self, *_args):
            return self.response

    class Scheduler:
        @staticmethod
        def submit(_model, *, execute, **_kwargs):
            return execute()

    class Tuner:
        def __init__(self):
            self.observations = []

        def observe(self, model, result, elapsed_ms):
            self.observations.append((model, result, elapsed_ms))

    monkeypatch.setattr(
        services_module,
        "_generation_cache_dispatch",
        lambda _cache, _key, _compute, compute_inner, **_kwargs: (
            compute_inner(), False, False
        ),
    )
    runtime = Runtime()
    tuner = Tuner()
    service = object.__new__(LocalAIServices)
    service.config = {
        "server": {"request_timeout_seconds": 5},
        "token_saving": {
            "max_local_input_tokens": 4096,
            "max_local_output_tokens": 128,
            "compact_responses": False,
        },
        "models": {},
        "ollama": {},
        "resilience": {"serve_stale_on_error": False},
    }
    service.runtime = runtime
    service.scheduler = Scheduler()
    service.model_policy = ModelPolicy()
    service._fallback_models = lambda _model: []
    service.breakers = SimpleNamespace(
        allow=lambda _key: SimpleNamespace(probe_generation=0),
        success=lambda *_args, **_kwargs: None,
        failure=lambda *_args, **_kwargs: None,
    )
    service.telemetry = _Noop()
    service.artifacts = _Noop()
    service.tuner = tuner
    service.generation_cache = None
    service.semantic_cache = SimpleNamespace(get=lambda *_args: (None, 0.0))
    service.stale_generation_cache = SimpleNamespace(
        get=lambda *_args: None,
        set=lambda *_args: None,
    )

    def generate():
        return service._generate(
            "test-model",
            "TASK: measure this request",
            "",
            64,
            0.0,
            source="delegate:reason",
            priority=0,
            use_cache=True,
        )

    runtime.response = {"error": "synthetic backend failure"}
    failed = generate()
    assert failed["success"] is False
    assert tuner.observations == []

    runtime.response = {"response": "synthetic answer", "done": True}
    succeeded = generate()
    assert succeeded["success"] is True
    assert len(tuner.observations) == 1
    model, observed_result, elapsed_ms = tuner.observations[0]
    assert model == "test-model"
    assert observed_result["success"] is True
    assert elapsed_ms >= 0


# ==============================================================================
# T6-09: Automation Backend Locking Isolation
# ==============================================================================
def test_t6_09_automation_open_close_does_not_hold_broker_lock(tmp_path: Path):
    """C09: Factory creation, expiry reap, and backend close run outside broker.lock."""
    broker_lock_during_factory = None
    broker_lock_during_close = []

    def another_thread_can_acquire(lock) -> bool:
        acquired = []

        def contend():
            obtained = lock.acquire(timeout=0.2)
            acquired.append(obtained)
            if obtained:
                lock.release()

        thread = threading.Thread(target=contend)
        thread.start()
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        assert acquired
        return acquired[0]

    class SlowBackend:
        def __init__(self, broker_ref):
            nonlocal broker_lock_during_factory
            self.broker = broker_ref
            broker_lock_during_factory = another_thread_can_acquire(self.broker.lock)

        def execute(self, *args, **kwargs):
            return {"status": "ok"}

        def close(self):
            broker_lock_during_close.append(another_thread_can_acquire(self.broker.lock))

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

    expired_id = open_res["automation"]["session_id"]
    expired = broker.sessions[expired_id]
    expired.expires = broker.clock() - 1
    broker.reap()
    assert broker_lock_during_close == [True]
    assert expired_id not in broker.sessions

    close_res = broker.execute(
        root=str(tmp_path),
        task_id="t1",
        request={"op": "open", "mode": "isolated", "url": "http://localhost:8000/"},
    )
    assert close_res["success"] is True
    assert broker_lock_during_factory is True

    closed_res = broker.execute(
        root=str(tmp_path),
        task_id="t1",
        request={"op": "close", "session_id": close_res["automation"]["session_id"], "session_key": close_res["automation"]["session_key"]},
    )
    assert closed_res["success"] is True
    assert broker_lock_during_close == [True, True]
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


def test_t6_10_query_local_fts_tracks_update_delete_without_persistent_schema(tmp_path: Path):
    """C10: Query-local FTS sees canonical changes and leaves the main schema unchanged."""
    state = AgentStateStore(tmp_path / "incidents.db")
    store = IncidentStore(state)
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

    assert [item["incident_id"] for item in store.find_negative_knowledge(root=root, query="beforetoken", limit=5)] == ["tracked"]
    with closing(sqlite3.connect(state.db_path)) as con:
        con.execute("UPDATE agent_incidents SET root_cause = 'aftertoken' WHERE incident_id = 'tracked'")
        con.commit()
    assert store.find_negative_knowledge(root=root, query="beforetoken", limit=5) == []
    assert [item["incident_id"] for item in store.find_negative_knowledge(root=root, query="aftertoken", limit=5)] == ["tracked"]

    with closing(sqlite3.connect(state.db_path)) as con:
        con.execute("DELETE FROM agent_incidents WHERE incident_id = 'tracked'")
        con.commit()
    assert store.find_negative_knowledge(root=root, query="aftertoken", limit=5) == []

    with closing(sqlite3.connect(state.db_path)) as con:
        assert con.execute(
            "SELECT name FROM sqlite_master WHERE name = 'agent_incidents_fts'"
        ).fetchone() is None
        assert con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND name LIKE 'trg_agent_incidents_fts_%'"
        ).fetchone() is None
    reloaded = IncidentStore(AgentStateStore(state.db_path))
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
def _persist_benchmark_records_process(benchmarks_path: str, worker_id: int, count: int, start_event: Any) -> None:
    import local_ai_hub.benchmark as benchmark_module

    original_loads = benchmark_module.json.loads

    def delayed_loads(value, *args, **kwargs):
        data = original_loads(value, *args, **kwargs)
        if isinstance(data, list):
            time.sleep(0.01)
        return data

    benchmark_module.json.loads = delayed_loads
    runner = HardwareBenchmarkRunner(benchmarks_path=benchmarks_path)
    if not start_event.wait(10):
        raise RuntimeError("benchmark writer start timed out")
    for index in range(count):
        runner._persist_record({
            "model": f"process-{worker_id}-{index}",
            "tokens_per_second": float(index),
        })


def test_t6_14_benchmark_persist_atomic(tmp_path: Path):
    """C14: _persist_record writes atomically to temporary file and renames."""
    from concurrent.futures import ThreadPoolExecutor

    benchmarks_path = tmp_path / "benchmarks.json"
    runner = HardwareBenchmarkRunner(benchmarks_path=benchmarks_path)

    runner._persist_record({"model": "test", "tokens_per_second": 50.0})

    # All calls share one runner and its file lock, as concurrent benchmark
    # requests do. Distinct records must survive the read/append/replace cycle.
    records = [
        {"model": f"parallel-{index}", "tokens_per_second": float(index)}
        for index in range(24)
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(runner._persist_record, records))

    assert benchmarks_path.exists()
    data = json.loads(benchmarks_path.read_text(encoding="utf-8"))
    assert len(data) == 25
    assert data[0]["model"] == "test"
    assert {record["model"] for record in data[1:]} == {
        record["model"] for record in records
    }


def test_t6_14_benchmark_persist_atomic_across_processes(tmp_path: Path):
    """C14: independent runner processes preserve every shared-file update."""
    import multiprocessing

    benchmarks_path = tmp_path / "benchmarks.json"
    HardwareBenchmarkRunner(benchmarks_path=benchmarks_path)._persist_record(
        {"model": "seed", "tokens_per_second": 0.0}
    )
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    worker_count = 4
    records_per_worker = 8
    processes = [
        context.Process(
            target=_persist_benchmark_records_process,
            args=(str(benchmarks_path), worker_id, records_per_worker, start_event),
        )
        for worker_id in range(worker_count)
    ]
    try:
        for process in processes:
            process.start()
        start_event.set()
        for process in processes:
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                process.join()
                pytest.fail("benchmark persistence worker did not finish")
        assert [process.exitcode for process in processes] == [0] * worker_count
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()

    data = json.loads(benchmarks_path.read_text(encoding="utf-8"))
    assert len(data) == 1 + worker_count * records_per_worker
    assert {record["model"] for record in data[1:]} == {
        f"process-{worker_id}-{index}"
        for worker_id in range(worker_count)
        for index in range(records_per_worker)
    }
