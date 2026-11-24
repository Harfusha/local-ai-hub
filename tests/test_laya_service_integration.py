from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest

import local_ai_hub.project_config as project_config
from local_ai_hub.app import LocalAIApp
from local_ai_hub.services import LocalAIServices


def test_app_context_exit_closes_laya_and_owned_background_resources(monkeypatch) -> None:
    app = LocalAIApp.__new__(LocalAIApp)
    app._shutdown = Event()
    app._close_lock = Lock()
    app._closed = False
    app._prewarm_thread = None
    app._watchdog_thread = None
    closed: list[str] = []

    class CloseSpy:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self, *args, **kwargs):
            closed.append(self.name)

    class ExecutorSpy:
        def shutdown(self, **_kwargs):
            closed.append("status_executor")

    app.async_jobs = CloseSpy("async_jobs")
    app.laya_lifecycle = CloseSpy("laya_lifecycle")
    app.background_gpu = CloseSpy("background_gpu")
    app.execution_pool = CloseSpy("execution_pool")
    app.external_tools = CloseSpy("external_tools")
    app.endpoint_stats = CloseSpy("endpoint_stats")
    app.telemetry = CloseSpy("telemetry")
    app._status_dependency_executor = ExecutorSpy()
    monkeypatch.setattr("local_ai_hub.app_runtime.shutdown_logging", lambda: None)

    with app as entered:
        assert entered is app

    assert app._shutdown.is_set()
    assert app._closed is True
    assert set(closed) == {
        "async_jobs", "laya_lifecycle", "background_gpu", "execution_pool",
        "external_tools", "endpoint_stats", "telemetry", "status_executor",
    }
    app.close()
    assert len(closed) == 8


@pytest.mark.parametrize(
    ("agent_header", "expected"),
    [
        ("codex-cli", "codex"),
        ("antigravity/1.0", "antigravity"),
        ("claude/3.7", "claude"),
        ("cursor-ide", "cursor"),
        ("windsurf-cascade", "windsurf"),
        ("vscode/1.96", "vscode"),
        ("copilot-chat", "copilot"),
        ("opencode-local", "opencode"),
        ("devin-local", "devin"),
        ("gemini-cli", "gemini_cli"),
        ("unrecognized", "generic_mcp"),
    ],
)
def test_laya_provider_attribution_uses_normalized_request_context(monkeypatch, agent_header, expected):
    from local_ai_hub import trace_context
    from local_ai_hub.app_laya_runtime import _current_laya_provider_label

    monkeypatch.setenv("LOCAL_AI_AGENT", "codex")
    monkeypatch.setattr(trace_context, "current_agent", lambda: agent_header)
    assert _current_laya_provider_label() == expected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("codex", "codex"),
        ("antigravity", "antigravity"),
        ("gemini_cli", "gemini_cli"),
        ("claude", "claude"),
        ("cursor", "cursor"),
        ("windsurf", "windsurf"),
        ("copilot", "copilot"),
        ("opencode", "opencode"),
        ("devin", "devin"),
    ],
)
def test_laya_provider_attribution_uses_stdio_provider_when_no_request_identity(
    monkeypatch, provider, expected
):
    from local_ai_hub import trace_context
    from local_ai_hub.app_laya_runtime import _current_laya_provider_label

    monkeypatch.setenv("LOCAL_AI_AGENT", provider)
    monkeypatch.setattr(trace_context, "current_agent", lambda: "")

    assert _current_laya_provider_label() == expected


def test_concurrent_laya_provider_attribution_stays_request_scoped(monkeypatch):
    from local_ai_hub import http_api_auth, http_api_request, trace_context
    from local_ai_hub.app_laya_runtime import _current_laya_provider_label

    requests = (
        ("codex-cli", "codex"),
        ("claude/3.7", "claude"),
        ("cursor-ide", "cursor"),
    )
    overlap = Barrier(len(requests))
    monkeypatch.setattr(http_api_request.services_module, "APP", None)

    class RequestProbe(http_api_auth.HttpAuthorizationMixin, http_api_request.HttpRequestMixin):
        def __init__(self, agent_header: str):
            self.headers = {"X-LocalAI-Agent": agent_header}

    def resolve(header: str) -> str:
        request = RequestProbe(header)
        request._begin_trace("/api/test")
        try:
            overlap.wait(timeout=3)
            observed = _current_laya_provider_label()
            overlap.wait(timeout=3)
            assert trace_context.current_agent() == header
        finally:
            request._close_trace_context()
        assert trace_context.current_agent() == ""
        return observed

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        observed = list(pool.map(resolve, (header for header, _expected in requests)))

    assert observed == [expected for _header, expected in requests]
    assert trace_context.current_agent() == ""


def test_app_close_keeps_gpu_services_open_when_laya_release_is_unconfirmed() -> None:
    class FailedLayaLifecycle:
        def close(self, **_kwargs):
            raise TimeoutError("unconfirmed")

    class MustStayOpenGpuWorker:
        def close(self):
            raise AssertionError("GPU services must stay open until Laya release is confirmed")

    app = LocalAIApp.__new__(LocalAIApp)
    app._shutdown = Event()
    app._close_lock = Lock()
    app._closed = False
    app._prewarm_thread = None
    app._watchdog_thread = None
    app.async_jobs = type("Jobs", (), {"close": lambda _self: None})()
    app.laya_lifecycle = FailedLayaLifecycle()
    app.background_gpu = MustStayOpenGpuWorker()

    assert app.close() is False
    assert app._shutdown.is_set()
    assert app._closed is False


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

    assert app._record_laya_capture_observation("captured", "runtime_outcome") is True
    assert recorded == [{
        "action": "laya_capture",
        "stage": "captured",
        "bypass_reason": "runtime_outcome",
        "success": True,
    }]

    def fail_recording(**_event: object) -> None:
        raise ValueError("private payload must not reach telemetry")

    app.telemetry.record_stage = fail_recording
    assert app._record_laya_capture_observation(
        "failed", "capture_exception", error_type="ValueError"
    ) is False
    assert warnings == [("Laya capture telemetry failed: %s", ("ValueError",))]








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


def test_laya_subagent_budget_baseline_defaults_to_single_agent_with_linked_evidence() -> None:
    from local_ai_hub.laya_decisions import DecisionCategory

    app = LocalAIApp.__new__(LocalAIApp)
    evidence_id = "E" + "a" * 20
    request = SimpleNamespace(
        category=DecisionCategory.SUBAGENT_BUDGET,
        evidence_ids=(evidence_id,),
        options=("single_agent", "parallel_split", "swarm"),
    )
    task = SimpleNamespace(checkpoint=SimpleNamespace(evidence_ids=(evidence_id,)))

    assert app._derive_laya_decision_baseline(request, task) == {
        "method": "agent_os_delegation_budget",
        "suggestion": "single_agent",
        "evidence_id": evidence_id,
    }

    request_without_safe_option = SimpleNamespace(
        category=DecisionCategory.SUBAGENT_BUDGET,
        evidence_ids=(evidence_id,),
        options=("parallel_split", "swarm"),
    )
    assert app._derive_laya_decision_baseline(request_without_safe_option, task) is None
















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
