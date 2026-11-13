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


def test_rejected_completion_queues_typed_shadow_gap_decision(tmp_path) -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    callbacks = []
    decisions = []
    task = SimpleNamespace(checkpoint=SimpleNamespace(evidence_ids=("ev-verified-1",)))
    app._status_dependency_executor = SimpleNamespace(
        submit=lambda callback: callbacks.append(callback) or Future()
    )
    app._shutdown = None
    app._laya_capture_lock = Lock()
    app._laya_capture_queue = []
    app._laya_capture_draining = False
    app.telemetry = SimpleNamespace(record_stage=lambda **_event: None)
    app.agent_tasks = object()
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda _store, root, task_id: task,
        _session_for_task=lambda _task: "session-1",
    )
    app.queue_laya_decision_observation = lambda operation, root, baseline: (
        decisions.append((operation, root, baseline)) or {"status": "queued"}
    )
    operation = {
        "task_id": "task-1",
        "session_id": "session-1",
        "outcome": {
            "status": "rejected",
            "reason_code": "completion_gate_rejected",
            "duration_ms": 8.0,
            "repository_revision": "a" * 40,
            "mutation_generation": 2,
        },
    }

    result = app.queue_laya_completion_observation(operation, str(tmp_path))

    assert result == {"status": "queued", "reason": "completion_outcome"}
    assert len(decisions) == 1
    decision, root, baseline = decisions[0]
    assert root == str(tmp_path)
    assert decision["decision"] == {
        "category": "completion_gap",
        "evidence_ids": ["ev-verified-1"],
        "options": ["missing_verification", "request_human_review", "resolve_blocker"],
        "state": {
            "completion_status": "not_ready",
            "reason_code": "completion_gate_rejected",
            "mutation_generation": "2",
        },
        "training_content": {},
    }
    assert baseline == {
        "method": "agent_os_completion_gate",
        "suggestion": "not_ready",
        "evidence_id": "ev-verified-1",
    }


def test_completion_outcome_without_task_id_is_skipped_before_queueing() -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    telemetry_events = []
    app._status_dependency_executor = SimpleNamespace(
        submit=lambda *_args: (_ for _ in ()).throw(AssertionError("invalid completion must not queue"))
    )
    app._shutdown = None
    app._laya_capture_lock = Lock()
    app._laya_capture_queue = []
    app._laya_capture_draining = False
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))
    operation = {
        "task_id": "",
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

    assert result == {"status": "skipped", "reason": "completion_scope_unavailable"}
    assert app._laya_capture_queue == []
    assert [event["stage"] for event in telemetry_events] == ["skipped"]
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
    assert observations[0]["decision"]["state"]["generator_model"] == "fast-model"
    assert observations[0]["decision"]["training_content"] == {
        "task_input": "Fix the parser.",
        "model_response": "done",
    }


def test_laya_model_response_excerpt_is_bounded_and_success_only() -> None:
    assert LocalAIServices._laya_model_response_excerpt({"success": False, "text": "partial"}) == ""
    excerpt = LocalAIServices._laya_model_response_excerpt({"success": True, "text": "🙂" * 5000})

    assert excerpt
    assert len(excerpt.encode("utf-8")) <= 8192


def test_solve_repo_queues_task_scoped_pipeline_response_for_laya() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    captured_args: list[dict] = []
    input_args = {
        "root": "C:/repo",
        "task_id": "task-pipeline-1",
        "task": "Implement the bounded parser change.",
    }
    result = {
        "success": True,
        "text": "Verified answer.",
        "canonical": {
            "route": {"task_type": "heavy_code", "complexity": "heavy", "semantic_required": True},
            "worker": {"used": True, "model": "qwen3.5:9b"},
        },
        "repo_context": {"evidence": [{"evidence_id": "ev-pipeline-1"}]},
        "pipeline": {"stages": ["worker"]},
    }
    def solve_repo(args):
        captured_args.append(args)
        callback = args.get("_laya_tool_output_callback")
        if callable(callback):
            callback("evidence_get", {"success": True, "text": "verified excerpt"})
        return result

    service.pipeline = SimpleNamespace(enabled=True, solve_repo=solve_repo)
    observations: list[dict] = []
    service.laya_decision_observer = lambda operation, _root, _baseline: (
        observations.append(operation) or {"status": "queued"}
    )

    actual = service.solve_repo(input_args)

    assert actual is result
    assert "_laya_tool_output_callback" not in input_args
    assert callable(captured_args[0]["_laya_tool_output_callback"])
    assert observations[0]["task_id"] == "task-pipeline-1"
    assert observations[0]["decision"]["category"] == "model_route"
    assert observations[0]["decision"]["evidence_ids"] == ["ev-pipeline-1"]
    assert observations[0]["decision"]["state"]["generator_model"] == "qwen3.5:9b"
    assert observations[0]["decision"]["training_content"] == {
        "task_input": "Implement the bounded parser change.",
        "model_response": "Verified answer.",
        "tool_output_excerpt": '{"output":{"success":true,"text":"verified excerpt"},"tool":"evidence_get"}',
    }


def test_solve_repo_does_not_label_deterministic_answer_as_model_response() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    service.pipeline = SimpleNamespace(solve_repo=lambda _args: {
        "success": True,
        "text": "Deterministic answer.",
        "canonical": {
            "route": {"task_type": "fast_code", "complexity": "fast", "semantic_required": False},
            "worker": {"used": False, "model": "deterministic"},
        },
        "repo_context": {"evidence": [{"evidence_id": "ev-deterministic-1"}]},
        "pipeline": {"stages": ["deterministic"]},
    })
    observations: list[dict] = []
    service.laya_decision_observer = lambda operation, *_args: observations.append(operation) or {"status": "queued"}

    service.solve_repo({
        "root": "C:/repo",
        "task_id": "task-deterministic-1",
        "task": "Find the declared symbol.",
    })

    assert observations == []


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
    service.delegate = lambda _payload, **_kwargs: {
        "success": True,
        "text": "done",
        "route": {"model": "selected-model"},
    }
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
    assert observations[0]["decision"]["state"]["generator_model"] == "selected-model"
    assert observations[0]["decision"]["training_content"] == {
        "task_input": "Summarize the module.",
        "model_response": "done",
    }


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

    completion_gap_operation = {
        **operation,
        "decision": {
            "category": "completion_gap",
            "evidence_ids": ["ev-1"],
            "options": ["missing_verification", "resolve_blocker"],
            "state": {"completion_status": "not_ready", "reason_code": "completion_gate_rejected"},
            "training_content": {},
        },
    }
    completion_gap_baseline = {
        "method": "agent_os_completion_gate",
        "suggestion": "not_ready",
        "evidence_id": "ev-1",
    }
    completion_gap_queued = app.queue_laya_decision_observation(
        completion_gap_operation,
        str(tmp_path),
        completion_gap_baseline,
    )

    assert queued == {"status": "queued"}
    assert rejected == {"status": "skipped", "reason": "decision_invalid"}
    assert completion_gap_queued == {"status": "queued"}
    assert len(app._laya_capture_queue) == 2
    queued_operation, queued_root, queued_baseline = app._laya_capture_queue[0]
    assert "session_id" not in queued_operation
    assert queued_root == str(tmp_path)
    assert queued_baseline == baseline


def test_successful_incomplete_task_context_queues_natural_laya_capture(tmp_path) -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {"laya": {"runtime": {
        "checkpoint_path": "pinned-local-checkpoint",
        "revision": "pinned-revision",
        "expected_sha256": {"model.safetensors": "a" * 64},
    }}}
    callbacks = []
    telemetry_events = []
    stored_sources = []
    verified_sources = []

    class _Executor:
        def submit(self, callback):
            callbacks.append(callback)
            return Future()

    app.agent_tasks = object()
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda _store, root, task_id: (
            object() if root == str(tmp_path) and task_id == "task-1" else None
        ),
        _session_for_task=lambda _task: "session-1",
    )

    def store_evidence(_root, _rows, *, source_code):
        stored_sources.append(source_code)
        return [{"evidence_id": "ev-indexed"}]

    def verify_evidence(evidence_ids, *, verify, root):
        assert verify is True
        assert root == str(tmp_path)
        return [{
            "success": True,
            "evidence_id": evidence_ids[0],
            "root": root,
            "stale": False,
        }]

    def verify_provenance(evidence_ids, source_codes, *, root):
        verified_sources.append((evidence_ids, source_codes, root))
        return root == str(tmp_path) and evidence_ids == ["ev-rag"] and source_codes == ["rag"]

    app.evidence = SimpleNamespace(
        put_many=store_evidence,
        get_many=verify_evidence,
        validate_source_provenance=verify_provenance,
    )
    app._status_dependency_executor = _Executor()
    app._laya_capture_lock = Lock()
    app._laya_capture_queue = []
    app._laya_capture_draining = False
    app._shutdown = SimpleNamespace(is_set=lambda: False)
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))
    app.logger = SimpleNamespace(warning=lambda *_args: None)

    request = SimpleNamespace(
        root=str(tmp_path),
        task_id="task-1",
        session_id="session-1",
        query="Find the missing source evidence.",
    )
    result = {
        "success": True,
        "stale": False,
        "retrieval": {
            "backend_states": {"lexical": "used", "rag": "used"},
            "lexical": {
                "freshness": {"status": "current"},
                "coverage": {"complete": False, "candidate_count": 1},
            },
            "semantic": {
                "freshness": {"status": "current"},
                "coverage": {"complete": False, "candidate_count": 1},
            },
        },
        "evidence": [
            {
                "semantic": False,
                "path": "src/indexed.py",
                "content_hash": "a" * 64,
                "text": "Indexed source evidence.",
            },
            {
                "semantic": True,
                "path": "docs/rag.md",
                "content_hash": "b" * 64,
                "evidence_id": "ev-rag",
                "text": "Retrieved RAG evidence.",
            },
        ],
    }

    observation = app.capture_laya_context_source_from_context(request, result)

    assert observation == {"status": "queued"}
    assert len(callbacks) == 1
    assert len(app._laya_capture_queue) == 1
    operation, queued_root, baseline = app._laya_capture_queue[0]
    assert queued_root == str(tmp_path)
    assert operation == {
        "action": "evaluate_context_source",
        "task_id": "task-1",
        "session_id": "session-1",
        "evidence": {
            "gap_code": "unresolved_evidence_gap",
            "source_codes": ["indexed", "rag"],
            "freshness_codes": ["current", "current"],
            "coverage_codes": ["partial", "partial"],
            "evidence_ids": ["ev-indexed", "ev-rag"],
            "source_record_ids": [None, None],
            "training_content": {
                "task_input": "Find the missing source evidence.",
                "context_excerpt": "indexed: Indexed source evidence.\nrag: Retrieved RAG evidence.",
            },
        },
    }
    assert baseline == {
        "method": "retrieval_rank_order",
        "suggestion": "indexed",
        "evidence_id": "ev-indexed",
    }
    assert stored_sources == ["indexed"]
    assert verified_sources == [(["ev-rag"], ["rag"], str(tmp_path))]
    assert [event["stage"] for event in telemetry_events] == ["queued"]
    assert all(
        not {"operation", "root", "query", "context_excerpt"}.intersection(event)
        for event in telemetry_events
    )


def test_context_source_capture_skips_without_task_identity(tmp_path) -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    telemetry_events = []
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))

    observation = app.capture_laya_context_source_from_context(
        SimpleNamespace(root=str(tmp_path), task_id="", session_id="", query="raw user query"),
        {"success": True},
    )

    assert observation == {"status": "skipped", "reason": "task_identity_unavailable"}
    assert [event["stage"] for event in telemetry_events] == ["skipped"]
    assert all("raw user query" not in str(event) for event in telemetry_events)


def test_context_source_capture_skips_when_checkpoint_is_not_configured(tmp_path) -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    telemetry_events = []
    app.config = {"laya": {"runtime": {
        "checkpoint_path": "", "revision": "", "expected_sha256": {},
    }}}
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))

    observation = app.capture_laya_context_source_from_context(
        SimpleNamespace(
            root=str(tmp_path), task_id="task-1", session_id="session-1",
            query="private raw task text",
        ),
        {"success": True},
    )

    assert observation == {"status": "skipped", "reason": "checkpoint_unavailable"}
    assert [event["stage"] for event in telemetry_events] == ["skipped"]
    assert [event["bypass_reason"] for event in telemetry_events] == ["checkpoint_unavailable"]
    assert "private raw task text" not in str(telemetry_events)
