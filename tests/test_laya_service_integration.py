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


def test_laya_capture_telemetry_is_metadata_only_and_logs_failures_safely() -> None:
    recorded: list[dict] = []
    warnings: list[tuple[str, tuple[object, ...]]] = []
    app = LocalAIApp.__new__(LocalAIApp)
    app.telemetry = SimpleNamespace(record_stage=lambda **event: recorded.append(event))
    app.logger = SimpleNamespace(warning=lambda message, *args: warnings.append((message, args)))

    assert app._record_laya_capture_observation("skipped", "no_unresolved_evidence_gap") is True
    assert recorded == [{
        "action": "laya_capture",
        "stage": "skipped",
        "bypass_reason": "no_unresolved_evidence_gap",
        "success": True,
    }]

    def fail_recording(**_event: object) -> None:
        raise ValueError("private payload must not reach telemetry")

    app.telemetry.record_stage = fail_recording
    assert app._record_laya_capture_observation(
        "failed", "capture_exception", error_type="ValueError"
    ) is False
    assert warnings == [("Laya capture telemetry failed: %s", ("ValueError",))]


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


def test_laya_shadow_observation_accepts_deterministic_delegation_baseline() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    observed: list[tuple[dict, str, dict]] = []
    service.laya_decision_observer = lambda operation, root, baseline: (
        observed.append((operation, root, baseline)) or {"status": "queued"}
    )

    queued = service._queue_laya_shadow_observation(
        {"task_id": "task-1", "evidence_ids": ["ev-1"]},
        root="C:/repo",
        category="delegation",
        options=["delegate_bounded", "no_delegation"],
        state={"worker_used": "false", "explorer_confidence": "high"},
        training_content={"task_input": "Inspect the repository change."},
        baseline={
            "method": "pipeline_worker_escalation",
            "suggestion": "no_delegation",
            "evidence_id": "ev-1",
        },
    )

    assert queued is True
    assert len(observed) == 1
    operation, root, baseline = observed[0]
    assert root == "C:/repo"
    assert operation["decision"]["category"] == "delegation"
    assert operation["decision"]["options"] == ["delegate_bounded", "no_delegation"]
    assert baseline["method"] == "pipeline_worker_escalation"
    assert baseline["suggestion"] == "no_delegation"


def test_laya_watchdog_baseline_uses_verified_agent_os_lifecycle_only() -> None:
    from local_ai_hub.agent_tasks import TaskStatus
    from local_ai_hub.laya_decisions import DecisionCategory

    app = LocalAIApp.__new__(LocalAIApp)
    request = SimpleNamespace(
        category=DecisionCategory.WATCHDOG,
        evidence_ids=("ev-task-1",),
        options=("recommend_continue", "recommend_stop", "recommend_human_review"),
    )

    for status, suggestion in (
        (TaskStatus.ACTIVE, "recommend_continue"),
        (TaskStatus.VERIFYING, "recommend_continue"),
        (TaskStatus.BLOCKED, "recommend_human_review"),
        (TaskStatus.WAITING, "recommend_human_review"),
        (TaskStatus.FAILED, "recommend_human_review"),
        (TaskStatus.ABANDONED, "recommend_human_review"),
        (TaskStatus.COMPLETED, "recommend_stop"),
        (TaskStatus.CANCELLED, "recommend_stop"),
    ):
        task = SimpleNamespace(
            task_id="task-1",
            status=status,
            checkpoint=SimpleNamespace(evidence_ids=("ev-task-1",)),
        )
        assert app._derive_laya_decision_baseline(request, task) == {
            "method": "agent_os_task_lifecycle",
            "suggestion": suggestion,
            "evidence_id": "ev-task-1",
        }

    task_without_linked_evidence = SimpleNamespace(
        task_id="task-1",
        status=TaskStatus.ACTIVE,
        checkpoint=SimpleNamespace(evidence_ids=("ev-other",)),
    )
    assert app._derive_laya_decision_baseline(request, task_without_linked_evidence) is None

    unsupported_status = SimpleNamespace(
        task_id="task-1",
        status="unknown",
        checkpoint=SimpleNamespace(evidence_ids=("ev-task-1",)),
    )
    assert app._derive_laya_decision_baseline(request, unsupported_status) is None

    limited_options = SimpleNamespace(
        category=DecisionCategory.WATCHDOG,
        evidence_ids=("ev-task-1",),
        options=("recommend_stop",),
    )
    active_task = SimpleNamespace(
        task_id="task-1",
        status=TaskStatus.ACTIVE,
        checkpoint=SimpleNamespace(evidence_ids=("ev-task-1",)),
    )
    assert app._derive_laya_decision_baseline(limited_options, active_task) is None


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
    assert [event["stage"] for event in telemetry_events] == ["skipped", "queued", "captured"]
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


def test_completion_next_step_uses_verified_task_context(tmp_path) -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    telemetry_events = []
    decisions = []
    task = SimpleNamespace(
        checkpoint=SimpleNamespace(evidence_ids=("ev-verified-1",)),
        contract=SimpleNamespace(acceptance_criteria=["Run focused validation", "Review the diff"]),
    )
    app.telemetry = SimpleNamespace(record_stage=lambda **event: telemetry_events.append(event))
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
        "outcome": {"status": "passed", "mutation_generation": 2},
    }

    result = app._queue_laya_completion_next_step_observation(operation, str(tmp_path))

    assert result == {"status": "queued"}
    decision, root, baseline = decisions[0]
    assert root == str(tmp_path)
    assert decision["decision"] == {
        "category": "next_step",
        "evidence_ids": ["ev-verified-1"],
        "options": ["ask_human", "inspect_source", "retrieve_evidence", "run_test"],
        "state": {
            "completion_status": "passed",
            "reason_code": "completion_validation_passed",
            "mutation_generation": "2",
        },
        "training_content": {"task_input": "Run focused validation\nReview the diff"},
    }
    assert baseline == {
        "method": "pipeline_step_progress",
        "suggestion": "ask_human",
        "evidence_id": "ev-verified-1",
    }
    assert telemetry_events == []


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
    assert [event["stage"] for event in telemetry_events] == ["skipped", "queued", "captured", "captured"]


def test_delegate_queues_model_route_observation_after_primary_generation() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service.router = _Router()
    route_models = {
        "fast_code": "fast-model",
        "heavy_code": "smart-model",
        "reasoning": "reasoning-model",
        "general": "generic-model",
    }
    service.router.model_for_role = lambda role: route_models[role]
    installed_models = {"fast-model", "generic-model"}
    service.runtime = SimpleNamespace(
        model_digest=lambda model: "a" * 64 if model in installed_models else None
    )
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
    assert observations[0]["decision"]["options"] == ["fast", "generic"]
    assert observations[0]["decision"]["state"]["generator_model"] == "fast-model"
    assert observations[0]["decision"]["training_content"] == {
        "task_input": "Fix the parser.",
        "model_response": "done",
    }


def test_laya_model_route_availability_uses_request_role_and_requires_two_routes() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    route_models = {
        "fast_code": "fast-model",
        "heavy_code": "smart-model",
        "reasoning": "reasoning-model",
        "general": "generic-model",
    }
    service.router = SimpleNamespace(model_for_role=lambda role: route_models[role])
    installed_models = {"fast-model", "reasoning-model"}
    service.runtime = SimpleNamespace(
        model_digest=lambda model: "b" * 64 if model in installed_models else None
    )

    assert service._available_laya_model_route_options("reasoning") == frozenset(
        {"fast", "smart"}
    )
    assert service._available_laya_model_route_options("fast_code") == frozenset()


def test_laya_model_route_availability_uses_project_resolved_models() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    route_models = {
        "fast_code": "base-fast",
        "heavy_code": "base-heavy",
        "reasoning": "base-reasoning",
        "general": "base-general",
    }
    project_models = {
        "fast_code": "project-fast",
        "heavy_code": "project-heavy",
        "reasoning": "project-reasoning",
        "general": "project-general",
    }
    settings = {"model_profile": "high"}
    policy_calls = []

    class _ModelPolicy:
        def apply_project_settings(self, model, payload, *, settings, role):
            policy_calls.append((model, settings, role))
            return project_models[role], payload

    service.router = SimpleNamespace(model_for_role=lambda role: route_models[role])
    service.model_policy = _ModelPolicy()
    installed_models = {"project-fast", "project-reasoning"}
    service.runtime = SimpleNamespace(
        model_digest=lambda model: "c" * 64 if model in installed_models else None
    )

    assert service._available_laya_model_route_options(
        "reasoning", project_settings=settings
    ) == frozenset({"fast", "smart"})
    assert policy_calls == [
        ("base-fast", settings, "fast_code"),
        ("base-heavy", settings, "heavy_code"),
        ("base-reasoning", settings, "reasoning"),
        ("base-general", settings, "general"),
    ]


def test_laya_model_route_availability_fails_closed_when_runtime_offline() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    route_models = {
        "fast_code": "fast-model",
        "heavy_code": "heavy-model",
        "reasoning": "reasoning-model",
        "general": "general-model",
    }
    service.router = SimpleNamespace(model_for_role=lambda role: route_models[role])
    digest_calls: list[str] = []
    service.runtime = SimpleNamespace(
        is_online=lambda: False,
        model_digest=lambda model: digest_calls.append(model) or "d" * 64,
    )

    assert service._available_laya_model_route_options("reasoning") == frozenset()
    assert digest_calls == []


def test_laya_model_route_availability_caches_verified_digests() -> None:
    service = LocalAIServices.__new__(LocalAIServices)
    route_models = {
        "fast_code": "fast-model",
        "heavy_code": "heavy-model",
        "reasoning": "heavy-model",
        "general": "general-model",
    }
    service.router = SimpleNamespace(model_for_role=lambda role: route_models[role])
    digest_calls: list[str] = []
    installed = {"fast-model": "a" * 64, "heavy-model": "b" * 64}

    def mock_digest(model: str) -> str | None:
        digest_calls.append(model)
        return installed.get(model)

    service.runtime = SimpleNamespace(is_online=lambda: True, model_digest=mock_digest)

    first = service._available_laya_model_route_options("reasoning")
    assert first == frozenset({"fast", "smart"})
    assert digest_calls == ["fast-model", "heavy-model", "general-model"]

    # Second call should reuse the cache without re-querying model_digest
    digest_calls.clear()
    second = service._available_laya_model_route_options("reasoning")
    assert second == frozenset({"fast", "smart"})
    assert digest_calls == []

    # use_cache=False bypasses the cache
    third = service._available_laya_model_route_options("reasoning", use_cache=False)
    assert third == frozenset({"fast", "smart"})
    assert digest_calls == ["fast-model", "heavy-model", "general-model"]


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
    route_models = {
        "fast_code": "fast-model",
        "heavy_code": "smart-model",
        "reasoning": "reasoning-model",
        "general": "generic-model",
    }
    service.router = SimpleNamespace(model_for_role=lambda role: route_models[role])
    service.runtime = SimpleNamespace(
        model_digest=lambda model: "d" * 64 if model in {"fast-model", "smart-model"} else None
    )
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
    assert observations[0]["decision"]["options"] == ["fast", "smart"]
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
    service.evidence_store = SimpleNamespace(get_many=lambda ids, **kwargs: [
        {
            "success": True,
            "evidence_id": "ev-1",
            "text": "Verified indexed source excerpt.",
            "source_verified": True,
            "stale": False,
        }
    ])
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
        "context_excerpt": "Verified indexed source excerpt.",
    }
    assert sum(
        len(value.encode("utf-8"))
        for value in observations[0]["decision"]["training_content"].values()
    ) < 16 * 1024


def test_laya_context_excerpt_requires_current_provenance_and_stays_bounded() -> None:
    calls: list[tuple[list[str], dict]] = []

    def get_many(ids, **kwargs):
        calls.append((ids, kwargs))
        return [
            {
                "success": True,
                "evidence_id": "ev-stale",
                "text": "Do not capture stale evidence.",
                "source_verified": False,
                "stale": True,
            },
            {
                "success": True,
                "evidence_id": "ev-current",
                "text": "x" * 7000,
                "source_verified": True,
                "stale": False,
            },
        ]

    excerpt = LocalAIServices._laya_verified_context_excerpt(
        SimpleNamespace(get_many=get_many),
        ["ev-stale", "ev-current"],
        root="C:/repo",
    )

    assert calls == [(["ev-stale", "ev-current"], {"verify": True, "root": "C:/repo"})]
    assert "Do not capture stale evidence." not in excerpt
    assert excerpt == "x" * (6 * 1024)


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

    delegation_operation = {
        **operation,
        "decision": {
            "category": "delegation",
            "evidence_ids": ["ev-1"],
            "options": ["delegate_bounded", "no_delegation"],
            "state": {
                "pipeline_mode": "adaptive",
                "review_task": "false",
                "planned_worker": "true",
                "worker_used": "true",
            },
            "training_content": {"task_input": "Fix the parser."},
        },
    }
    delegation_baseline = {
        "method": "pipeline_worker_escalation",
        "suggestion": "delegate_bounded",
        "evidence_id": "ev-1",
    }
    delegation_queued = app.queue_laya_decision_observation(
        delegation_operation,
        str(tmp_path),
        delegation_baseline,
    )

    assert queued == {"status": "queued"}
    assert rejected == {"status": "skipped", "reason": "decision_invalid"}
    assert completion_gap_queued == {"status": "queued"}
    assert delegation_queued == {"status": "queued"}
    assert len(app._laya_capture_queue) == 3
    queued_operation, queued_root, queued_baseline = app._laya_capture_queue[0]
    assert "session_id" not in queued_operation
    assert queued_root == str(tmp_path)
    assert queued_baseline == baseline


def test_app_accepts_server_derived_delegation_baseline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        project_config,
        "resolve_project_context",
        lambda *_args: SimpleNamespace(coordination_id="repo-1"),
    )
    captured_baselines = []

    class _Adapter:
        def evaluate_decision(self, request, decision_input, *, session_lifecycle, outcome_recorder):
            decision = SimpleNamespace(
                success=True,
                status=SimpleNamespace(value="ok"),
                suggestion="delegate_bounded",
                reason_codes=(),
            )
            outcome = SimpleNamespace(decision=decision, runtime=None)
            outcome_recorder(request, decision_input, outcome)
            return outcome

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
        capture_runtime_outcome=lambda _request, _input, _outcome, **kwargs: (
            captured_baselines.append(kwargs["baseline"]) or {"candidate_id": "candidate-1"}
        ),
    )
    app.evidence = object()
    app.laya_lifecycle = object()
    app._get_laya_runtime_adapter = lambda *_args, **_kwargs: _Adapter()
    app._record_laya_runtime_decision = lambda *_args: True
    operation = {
        "action": "evaluate_decision",
        "task_id": "task-1",
        "decision": {
            "category": "delegation",
            "evidence_ids": ["ev-1"],
            "options": ["delegate_bounded", "no_delegation"],
            "state": {"pipeline_mode": "adaptive", "review_task": "false"},
            "training_content": {},
        },
    }
    baseline = {
        "method": "pipeline_worker_escalation",
        "suggestion": "delegate_bounded",
        "evidence_id": "ev-1",
    }

    result = app.evaluate_laya_decision(operation, root=str(tmp_path), _server_baseline=baseline)

    assert result["success"] is True
    assert result["candidate"]["candidate_id"] == "candidate-1"
    assert captured_baselines == [baseline]


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

    memory_calls = []
    memory_record = SimpleNamespace(
        record_id="memory-1",
        scope=SimpleNamespace(value="task"),
        status=SimpleNamespace(value="active"),
        evidence_ids=("ev-memory",),
        value="Task-specific memory source.",
        sensitivity="normal",
    )
    app.agent_memory = SimpleNamespace(
        find=lambda **kwargs: (memory_calls.append(kwargs) or [memory_record])
    )
    result["retrieval"]["lexical"]["coverage"]["complete"] = True
    result["retrieval"]["semantic"]["coverage"]["complete"] = True
    callbacks.clear()
    telemetry_events.clear()
    app._laya_capture_queue.clear()
    app._laya_capture_draining = False

    observation = app.capture_laya_context_source_from_context(request, result)

    assert observation == {"status": "skipped", "reason": "no_unresolved_evidence_gap"}
    assert memory_calls == []
    assert callbacks == []
    assert app._laya_capture_queue == []
    assert [event["stage"] for event in telemetry_events] == ["skipped"]


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
