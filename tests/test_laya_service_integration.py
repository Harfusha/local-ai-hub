from __future__ import annotations

from concurrent.futures import Future
from threading import Lock
from types import SimpleNamespace

import local_ai_hub.project_config as project_config
from local_ai_hub.app import LocalAIApp
from local_ai_hub.services import LocalAIServices


class _Router:
    def classify(self, *_args):
        return {
            "task_type": "code",
            "complexity": "fast",
            "complexity_score": 1,
            "semantic_required": False,
            "model": "fast-model",
        }

    def apply_model_override(self, route, _model):
        return route


def test_laya_shadow_observation_queues_only_verified_scope_inputs() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    observed: list[tuple[dict, str, dict]] = []
    service.laya_decision_observer = lambda operation, root, baseline: (
        observed.append((operation, root, baseline)) or {"status": "queued"}
    )

    queued = service._queue_laya_shadow_observation(
        {
            "task_id": "task-1",
            "evidence_ids": ["ev-1"],
        },
        root="C:/repo",
        category="model_route",
        options=["fast", "smart"],
        state={"task_type": "code", "complexity": "fast"},
        training_content={"task_input": "Fix the parser."},
        baseline={
            "method": "model_router_classify",
            "suggestion": "fast",
            "evidence_id": "ev-1",
        },
    )

    assert queued is True
    assert len(observed) == 1
    operation, root, baseline = observed[0]
    assert root == "C:/repo"
    assert operation == {
        "action": "evaluate_decision",
        "task_id": "task-1",
        "decision": {
            "category": "model_route",
            "evidence_ids": ["ev-1"],
            "options": ["fast", "smart"],
            "state": {"task_type": "code", "complexity": "fast"},
            "training_content": {"task_input": "Fix the parser."},
        },
    }
    assert baseline["suggestion"] == "fast"


def test_laya_shadow_observation_skips_without_evidence_ids() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    service.laya_decision_observer = lambda *_args: (_ for _ in ()).throw(
        AssertionError("observer must not run without evidence")
    )

    queued = service._queue_laya_shadow_observation(
        {"task_id": "task-1"},
        root="C:/repo",
        category="context_budget",
        options=["compact", "standard", "expanded"],
        state={"complexity": "heavy", "context_budget": "expanded"},
        training_content={"task_input": "Summarize the module."},
        baseline={
            "method": "repo_context_token_budget",
            "suggestion": "expanded",
            "evidence_id": "ev-1",
        },
    )

    assert queued is False


def test_completion_outcome_is_queued_and_records_metadata_only() -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    callbacks = []
    telemetry_events = []
    candidate_calls = []
    app._status_dependency_executor = SimpleNamespace(
        submit=lambda callback: callbacks.append(callback) or Future()
    )
    app._shutdown = None
    app._laya_capture_lock = Lock()
    app._laya_capture_queue = []
    app._laya_capture_draining = False
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))
    app.laya_candidates = SimpleNamespace(
        record_completion_outcome=lambda operation, **kwargs: (
            candidate_calls.append((operation, kwargs)) or {"event_count": 1}
        )
    )
    app.agent_tasks = object()
    operation = {
        "task_id": "task-1",
        "session_id": "session-1",
        "outcome": {
            "status": "passed",
            "reason_code": "completion_gate_passed",
            "duration_ms": 8.0,
            "repository_revision": "a" * 40,
            "mutation_generation": 2,
        },
    }

    result = app.queue_laya_completion_observation(operation, "C:/repo")

    assert result == {"status": "queued", "reason": "completion_outcome"}
    assert len(callbacks) == 1
    assert candidate_calls == []
    callbacks[0]()

    assert candidate_calls == [(operation, {"root": "C:/repo", "task_store": app.agent_tasks})]
    assert [event["stage"] for event in telemetry_events] == ["queued", "captured"]
    assert all("operation" not in event and "root" not in event for event in telemetry_events)


def test_completion_outcome_waits_behind_queued_decision_capture() -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    callbacks = []
    events = []
    telemetry_events = []
    app._status_dependency_executor = SimpleNamespace(submit=lambda callback: callbacks.append(callback))
    app._shutdown = SimpleNamespace(is_set=lambda: False)
    app._laya_capture_lock = Lock()
    app._laya_capture_queue = [({"action": "evaluate_decision"}, "C:/repo", {})]
    app._laya_capture_draining = True
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))
    app.agent_tasks = object()
    app.logger = SimpleNamespace(warning=lambda *_args: None)
    app.evaluate_laya_decision = lambda *_args, **_kwargs: (
        events.append("decision") or {"candidate": {"candidate_id": "candidate-1"}}
    )
    app.laya_candidates = SimpleNamespace(
        record_completion_outcome=lambda *_args, **_kwargs: (
            events.append("completion") or {"event_count": 1}
        )
    )
    operation = {
        "task_id": "task-1",
        "session_id": "session-1",
        "outcome": {
            "status": "passed",
            "reason_code": "completion_gate_passed",
            "duration_ms": 8.0,
            "repository_revision": "a" * 40,
            "mutation_generation": 2,
        },
    }

    result = app.queue_laya_completion_observation(operation, "C:/repo")

    assert result == {"status": "queued", "reason": "completion_outcome"}
    assert callbacks == []
    assert len(app._laya_capture_queue) == 2
    app._drain_laya_capture_queue()

    assert events == ["decision", "completion"]
    assert [event["stage"] for event in telemetry_events] == ["queued", "captured", "captured"]


def test_delegate_queues_model_route_observation_after_primary_generation() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service.router = _Router()
    service._resolve_local_task_project = lambda _root: (None, "", "", "")
    service._resident_optimize = lambda route, *_args: route
    events: list[str] = []
    observations: list[dict] = []

    def generate(*_args, **_kwargs):
        events.append("generation")
        return {"success": True, "text": "done"}

    service._generate = generate
    service.laya_decision_observer = lambda operation, _root, _baseline: (
        events.append("laya_queue") or observations.append(operation) or {"status": "queued"}
    )

    result = service.delegate({
        "root": "C:/repo",
        "task_id": "task-1",
        "evidence_ids": ["ev-1"],
        "task": "Fix the parser.",
    })

    assert result["success"] is True
    assert events == ["generation", "laya_queue"]
    assert observations[0]["decision"]["category"] == "model_route"


def test_delegate_repo_queues_automatic_context_budget_with_retrieval_evidence() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"workflow": {"fast_repo_context_tokens": 2200, "heavy_repo_context_tokens": 4200}}
    service.router = _Router()
    service._hybrid_context = lambda *_args, **_kwargs: {
        "success": True,
        "root": "C:/repo",
        "context": "indexed source",
        "evidence": [{"evidence_id": "ev-1"}],
        "estimated_tokens": 12,
        "semantic_used": False,
        "scanned_files": 1,
    }
    observations: list[dict] = []
    service.delegate = lambda _payload, **_kwargs: {"success": True, "text": "done"}
    service.laya_decision_observer = lambda operation, _root, _baseline: (
        observations.append(operation) or {"status": "queued"}
    )

    result = service.delegate_repo({
        "root": "C:/repo",
        "task_id": "task-1",
        "task": "Summarize the module.",
    })

    assert result["success"] is True
    assert result["repo_context"]["evidence"] == [{"evidence_id": "ev-1"}]
    assert observations[0]["decision"]["category"] == "context_budget"
    assert observations[0]["decision"]["evidence_ids"] == ["ev-1"]


def test_app_queue_derives_scope_and_rejects_caller_baseline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        project_config,
        "resolve_project_context",
        lambda *_args: SimpleNamespace(coordination_id="repo-1"),
    )
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {
        "laya": {"runtime": {
            "checkpoint_path": "C:/models/laya/revision-1",
            "revision": "revision-1",
            "expected_sha256": {"model.safetensors": "a" * 64},
        }},
        "server": {"state_dir": str(tmp_path)},
    }
    app.agent_tasks = object()
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda *_args: object(),
        _session_for_task=lambda _task: "session-1",
        _candidate_input=lambda value: value,
        _validate_context_source_evidence=lambda *_args, **_kwargs: None,
    )
    app.evidence = object()
    statuses: list[tuple[str, str]] = []
    app._record_laya_capture_observation = lambda status, reason, **_kwargs: statuses.append((status, reason)) or True
    app._laya_capture_lock = Lock()
    app._laya_capture_queue = []
    app._laya_capture_draining = False
    app._shutdown = SimpleNamespace(is_set=lambda: False)

    class _Executor:
        def submit(self, _callback):
            future = Future()
            future.set_result(None)
            return future

    app._status_dependency_executor = _Executor()

    operation = {
        "action": "evaluate_decision",
        "task_id": "task-1",
        "decision": {
            "category": "model_route",
            "evidence_ids": ["ev-1"],
            "options": ["fast", "smart"],
            "state": {"task_type": "code", "complexity": "fast"},
            "training_content": {"task_input": "Fix the parser."},
        },
    }
    baseline = {"method": "model_router_classify", "suggestion": "fast", "evidence_id": "ev-1"}

    queued = app.queue_laya_decision_observation(operation, str(tmp_path), baseline)
    rejected = app.queue_laya_decision_observation(
        operation,
        str(tmp_path),
        {**baseline, "suggestion": "outside-options"},
    )

    assert queued == {"status": "queued"}
    assert rejected == {"status": "skipped", "reason": "decision_invalid"}
    assert len(app._laya_capture_queue) == 1
    queued_operation, queued_root, queued_baseline = app._laya_capture_queue[0]
    assert "session_id" not in queued_operation
    assert queued_root == str(tmp_path)
    assert queued_baseline == baseline
