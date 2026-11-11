import importlib
import os
import threading
from dataclasses import replace
from pathlib import Path

from local_ai_hub.laya_decisions import (
    ContextSourceCoverage,
    ContextSourceEvidence,
    ContextSourceFreshness,
    DecisionCategory,
    DecisionInput,
    DecisionMode,
    DecisionRequest,
    DecisionStatus,
)
from local_ai_hub.laya_lifecycle import LayaSessionLifecycle
from local_ai_hub.laya_runtime import (
    DeviceCandidate,
    LayaRuntimeAdapter,
    LayaRuntimeUnavailable,
    select_laya_device,
)


def _patch_laya_runtime_imports(monkeypatch, fake_laya):
    runtime_module = importlib.import_module("local_ai_hub.laya_runtime")
    monkeypatch.setattr(runtime_module.importlib, "import_module", lambda _name: fake_laya)
    monkeypatch.setattr(runtime_module.importlib.metadata, "version", lambda _name: "0.4.fixture")


REVISION = "1720e3e3357cfe1e281542e223f8273b0890ca34"
HASHES = {"model.safetensors": "a" * 64}


class FakeParameter:
    def __init__(self, device):
        self.device = device


class FakeModel:
    def __init__(self, device, output=None, entered=None, release=None):
        self.parameter = FakeParameter(device)
        self.output = output or {
            "answers": {"source": {"choice": "artifact"}},
            "usage": {"input_tokens": 31, "output_tokens": 4},
        }
        self.entered = entered
        self.release = release
        self.seen = None

    def parameters(self):
        return iter([self.parameter])

    def cpu(self):
        self.parameter.device = "cpu"


class FakeAgent:
    def __init__(self, device, output=None, entered=None, release=None):
        self.model = FakeModel(device, output, entered, release)

    def predict(self, state, questions):
        self.model.seen = (state, questions)
        if self.model.entered:
            self.model.entered.set()
            self.model.release.wait(2)
        return self.model.output

    def close(self):
        self.model.cpu()
        return self.model.parameter.device == "cpu"


class FakeRouter:
    def __init__(self, *, models, device, default, max_loaded, preload, sha256_digests, vega):
        self.config = {
            "models": models,
            "device": device,
            "default": default,
            "max_loaded": max_loaded,
            "preload": preload,
            "sha256_digests": sha256_digests,
            "vega": vega,
        }
        self._agents = {}
        self.unload_calls = []

    @property
    def loaded(self):
        return list(self._agents)

    def load(self, name):
        agent = FakeAgent(self.config["device"])
        self._agents[name] = agent
        return agent

    def predict(self, state, questions, *, model):
        return self._agents[model].predict(state, questions)

    def unload(self, name=None):
        self.unload_calls.append(name)
        if name is None:
            self._agents.clear()
        else:
            self._agents.pop(name, None)


def request_and_evidence():
    evidence = ContextSourceEvidence(
        gap_code="unresolved_evidence_gap",
        source_codes=("indexed", "artifact"),
        freshness_codes=(ContextSourceFreshness.CURRENT, ContextSourceFreshness.CURRENT),
        coverage_codes=(ContextSourceCoverage.PARTIAL, ContextSourceCoverage.COMPLETE),
        evidence_ids=("ev-index", "ev-artifact"),
    )
    request = DecisionRequest(
        decision_id="decision-1",
        mode=DecisionMode.SHADOW,
        category=DecisionCategory.CONTEXT_SOURCE,
        repository_id="repo-1",
        task_id="task-1",
        session_id="session-1",
        evidence_ids=evidence.evidence_ids,
        options=evidence.decision_options,
    )
    return request, evidence


def make_checkpoint(tmp_path: Path) -> Path:
    checkpoint = tmp_path / REVISION
    (checkpoint / "tokenizer").mkdir(parents=True)
    for filename in ("rl_agent_config.json", "model.safetensors", "tokenizer/tokenizer.json"):
        (checkpoint / filename).write_bytes(b"fixture")
    return checkpoint


def candidate(device, device_class="dgpu", *, quality_passed=None):
    return DeviceCandidate(
        provider="torch",
        device=device,
        device_class=device_class,
        device_name=f"fixture {device}",
        runtime_version="2.11.0",
        available=True,
        supports_laya=True,
        quality_passed=quality_passed,
    )


def adapter(
    tmp_path, loader, *, devices=None, evaluation_mode=True,
    capacity_manager=None, capacity_request_bytes=None,
):
    return LayaRuntimeAdapter(
        checkpoint_path=make_checkpoint(tmp_path),
        revision=REVISION,
        expected_sha256=HASHES,
        device_candidates=devices or [candidate("cuda:0")],
        evaluation_mode=evaluation_mode,
        loader=loader,
        capacity_manager=capacity_manager,
        capacity_request_bytes=capacity_request_bytes,
    )


def lifecycle():
    return LayaSessionLifecycle(0, close_session=lambda _session: True)


def test_runtime_adapter_evaluates_standalone_typed_decision_with_redacted_training_input(tmp_path):
    holder = {}

    def load(_path, *, device, expected_sha256):
        holder["agent"] = FakeAgent(
            device,
            output={"answers": {"source": {"choice": "run_test"}}, "usage": {}},
        )
        return holder["agent"]

    request = DecisionRequest(
        decision_id="decision-standalone",
        mode=DecisionMode.SHADOW,
        category=DecisionCategory.NEXT_STEP,
        repository_id="repo-1",
        task_id="task-1",
        session_id="session-1",
        evidence_ids=(),
        options=("inspect_source", "run_test"),
    )
    decision_input = DecisionInput.from_mapping(
        {
            "state": {"gap_code": "missing_verification"},
            "training_content": {"task_input": "Check token=secret-value and run focused test."},
        }
    )
    model = adapter(tmp_path, load)

    result = model.evaluate_decision(
        request,
        decision_input,
        session_lifecycle=lifecycle(),
    )

    assert result.decision.suggestion == "run_test"
    assert result.runtime is not None
    body = holder["agent"].model.seen[0]["body"]
    assert "raw_task_input" in body
    assert "[REDACTED]" in body
    assert "secret-value" not in body


def test_idle_timeout_starts_after_laya_outcome_recorder_finishes(tmp_path):
    now = [0.0]
    shared_lifecycle = LayaSessionLifecycle(
        600, close_session=lambda session: session.close(), clock=lambda: now[0]
    )
    model = adapter(tmp_path, lambda _path, *, device, expected_sha256: FakeAgent(device))
    request, evidence = request_and_evidence()

    def record_outcome(_request, _evidence, _outcome):
        now[0] = 500.0
        assert shared_lifecycle.poll_idle_unload(now=700.0) == "busy"

    result = model.evaluate_context_source(
        request,
        evidence,
        session_lifecycle=shared_lifecycle,
        outcome_recorder=record_outcome,
    )

    assert result.runtime is not None
    assert shared_lifecycle.poll_idle_unload(now=1099.0) == "not_idle"
    assert shared_lifecycle.poll_idle_unload(now=1100.0) == "unloaded"


def test_runtime_adapter_binds_provider_close_before_shared_session_use(tmp_path):
    holder = {}

    def load(_path, *, device, expected_sha256):
        holder["agent"] = FakeAgent(device)
        return holder["agent"]

    model = adapter(tmp_path, load)
    request, evidence = request_and_evidence()
    shared_lifecycle = LayaSessionLifecycle(1, clock=lambda: 1.0)

    result = model.evaluate_context_source(
        request, evidence, session_lifecycle=shared_lifecycle
    )

    assert result.runtime is not None
    assert shared_lifecycle.status["provider_close_configured"] is True
    assert shared_lifecycle.poll_idle_unload(now=2.0) == "unloaded"
    assert holder["agent"].model.parameter.device == "cpu"


def test_parameter_cpu_move_alone_is_not_provider_close_confirmation():
    class CpuOnlyAgent:
        model = FakeModel("cuda:0")

    assert LayaRuntimeAdapter._close(CpuOnlyAgent()) is False


def test_default_adapter_uses_one_local_router_checkpoint_and_unloads_it(tmp_path, monkeypatch):
    routers = []

    def make_router(**kwargs):
        router = FakeRouter(**kwargs)
        routers.append(router)
        return router

    fake_laya = type("FakeLaya", (), {"Router": staticmethod(make_router), "__version__": "fixture"})
    _patch_laya_runtime_imports(monkeypatch, fake_laya)
    model = adapter(tmp_path, None)
    request, evidence = request_and_evidence()
    shared_lifecycle = LayaSessionLifecycle(1, clock=lambda: 1.0)

    result = model.evaluate_context_source(request, evidence, session_lifecycle=shared_lifecycle)

    assert result.runtime is not None
    assert result.runtime.device == "cuda:0"
    assert len(routers) == 1
    router = routers[0]
    assert router.config["models"] == {"local-ai-hub-multilingual": str(model.checkpoint_path.resolve())}
    assert router.config["default"] == "local-ai-hub-multilingual"
    assert router.config["max_loaded"] == 1
    assert router.config["preload"] is False
    assert router.config["sha256_digests"] == {"local-ai-hub-multilingual": HASHES}
    assert router.config["vega"] is False
    assert router.loaded == ["local-ai-hub-multilingual"]
    assert shared_lifecycle.poll_idle_unload(now=2.0) == "unloaded"
    assert router.unload_calls == ["local-ai-hub-multilingual"]
    assert router.loaded == []


def test_router_unload_error_keeps_provider_session_and_reports_close_failure(tmp_path, monkeypatch):
    routers = []

    def make_router(**kwargs):
        router = FakeRouter(**kwargs)
        routers.append(router)
        return router

    fake_laya = type("FakeLaya", (), {"Router": staticmethod(make_router), "__version__": "fixture"})
    _patch_laya_runtime_imports(monkeypatch, fake_laya)
    model = adapter(tmp_path, None)
    request, evidence = request_and_evidence()
    shared_lifecycle = LayaSessionLifecycle(1, clock=lambda: 1.0)

    result = model.evaluate_context_source(request, evidence, session_lifecycle=shared_lifecycle)
    router = routers[0]
    router.unload = lambda _name=None: (_ for _ in ()).throw(OSError("provider close failed"))

    assert result.runtime is not None
    assert shared_lifecycle.poll_idle_unload(now=2.0) == "close_failed"
    assert shared_lifecycle.status["available"] is True
    assert shared_lifecycle.status["last_close_error"] == "OSError"
    assert router.loaded == ["local-ai-hub-multilingual"]


def test_adapter_preserves_preconfigured_provider_close_callback(tmp_path):
    holder = {}
    close_calls = []

    def load(_path, *, device, expected_sha256):
        holder["agent"] = FakeAgent(device)
        return holder["agent"]

    model = adapter(tmp_path, load)
    request, evidence = request_and_evidence()
    shared_lifecycle = LayaSessionLifecycle(
        1, close_session=lambda session: (close_calls.append(session) or True),
        clock=lambda: 1.0,
    )

    result = model.evaluate_context_source(
        request, evidence, session_lifecycle=shared_lifecycle
    )

    assert result.runtime is not None
    assert shared_lifecycle.poll_idle_unload(now=2.0) == "unloaded"
    assert close_calls == [holder["agent"]]
    assert holder["agent"].model.parameter.device == "cuda:0"


def test_device_selection_requires_quality_for_non_evaluation_use():
    gpu = candidate("cuda:0", quality_passed=None)
    npu = candidate("npu:0", "npu", quality_passed=True)
    assert select_laya_device([gpu, npu]).device == "npu:0"
    try:
        select_laya_device([gpu])
    except RuntimeError as exc:
        assert "quality gate" in str(exc)
    else:
        raise AssertionError("unknown quality must not qualify a production device")
    assert select_laya_device([gpu], evaluation_mode=True) is gpu


def test_disabled_adapter_does_not_load_or_infer(tmp_path):
    calls = []
    model = adapter(tmp_path, lambda *args, **kwargs: calls.append((args, kwargs)), evaluation_mode=False)
    request, evidence = request_and_evidence()
    result = model.evaluate_context_source(request, evidence, session_lifecycle=lifecycle())
    assert result.decision.status is DecisionStatus.SKIPPED
    assert result.decision.reason_codes == ("DISABLED",)
    assert calls == []


def test_adapter_rejects_advisory_mode_before_loading(tmp_path):
    calls = []
    model = adapter(tmp_path, lambda *args, **kwargs: calls.append((args, kwargs)))
    request, evidence = request_and_evidence()
    advisory_request = replace(request, mode=DecisionMode.ADVISORY)
    try:
        model.evaluate_context_source(advisory_request, evidence, session_lifecycle=lifecycle())
    except ValueError as exc:
        assert "shadow" in str(exc)
    else:
        raise AssertionError("explicit runtime adapter must reject advisory requests")
    assert calls == []


def test_context_source_uses_redacted_training_content_and_returns_unverified_runtime(tmp_path):
    holder = {}

    def load(_path, *, device, expected_sha256):
        holder["args"] = (device, expected_sha256)
        holder["agent"] = FakeAgent(device)
        return holder["agent"]

    model = adapter(tmp_path, load)
    request, evidence = request_and_evidence()
    evidence = replace(
        evidence,
        training_content={
            "task_input": "Find parser behavior for token=secret-value",
            "context_excerpt": "parser.py checks the requested route",
        },
    )
    result = model.evaluate_context_source(request, evidence, session_lifecycle=lifecycle())
    assert result.decision.suggestion == "artifact"
    assert holder["args"] == ("cuda:0", HASHES)
    state, questions = holder["agent"].model.seen
    assert "ev-artifact" in state["body"]
    assert "Find parser behavior for token=[REDACTED]" in state["body"]
    assert "parser.py checks the requested route" in state["body"]
    assert "secret-value" not in state["body"]
    assert questions["source"]["type"] == "choice"
    assert set(questions["source"]["criteria"]) == {"indexed", "artifact"}
    assert result.runtime.execution_verification == "NOT_VERIFIED"
    assert result.runtime.quality_status == "NOT_EVALUATED"
    assert result.runtime.input_tokens == 31
    assert result.runtime.output_tokens == 4


def test_invalid_output_is_rejected_without_exposing_raw_result(tmp_path):
    def load(_path, *, device, expected_sha256):
        return FakeAgent(device, {"answers": {"source": {"choice": "execute_tool"}}, "private": "never return"})

    model = adapter(tmp_path, load)
    request, evidence = request_and_evidence()
    result = model.evaluate_context_source(request, evidence, session_lifecycle=lifecycle())
    assert result.decision.status is DecisionStatus.ERROR
    assert result.decision.reason_codes == ("INVALID_OUTPUT",)
    assert "private" not in result.decision.metadata()


def test_missing_answer_abstains(tmp_path):
    model = adapter(tmp_path, lambda _path, *, device, expected_sha256: FakeAgent(device, {"answers": {}}))
    request, evidence = request_and_evidence()
    result = model.evaluate_context_source(request, evidence, session_lifecycle=lifecycle())
    assert result.decision.status is DecisionStatus.ABSTAIN
    assert result.decision.reason_codes == ("LOW_SIGNAL",)


def test_provider_failure_falls_back_once_to_next_eligible_device(tmp_path):
    attempts = []

    def load(_path, *, device, expected_sha256):
        attempts.append(device)
        if device == "cuda:0":
            raise RuntimeError("private provider failure")
        return FakeAgent(device)

    devices = [candidate("cuda:0"), candidate("cpu", "cpu")]
    model = adapter(tmp_path, load, devices=devices)
    request, evidence = request_and_evidence()
    result = model.evaluate_context_source(request, evidence, session_lifecycle=lifecycle())
    assert result.decision.suggestion == "artifact"
    assert attempts == ["cuda:0", "cpu"]
    assert result.runtime.device == "cpu"
    assert result.runtime.fallback_reason == "EARLIER_DEVICE_UNAVAILABLE"


def test_concurrent_evaluation_is_rejected_as_overloaded(tmp_path):
    entered, release = threading.Event(), threading.Event()
    model = adapter(tmp_path, lambda _path, *, device, expected_sha256: FakeAgent(device, entered=entered, release=release))
    request, evidence = request_and_evidence()
    output = []
    worker = threading.Thread(
        target=lambda: output.append(model.evaluate_context_source(request, evidence, session_lifecycle=lifecycle()))
    )
    worker.start()
    assert entered.wait(2)
    second = model.evaluate_context_source(request, evidence, session_lifecycle=lifecycle())
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert second.decision.status is DecisionStatus.SKIPPED
    assert second.decision.reason_codes == ("OVERLOADED",)
    assert output[0].decision.suggestion == "artifact"


def test_unconfirmed_provider_cleanup_stops_device_fallback(tmp_path):
    attempts = []

    class UncloseableAgent(FakeAgent):
        def close(self):
            return False

    def load(_path, *, device, expected_sha256):
        attempts.append(device)
        if device == "cuda:0":
            return UncloseableAgent("cpu")
        return FakeAgent(device)

    model = adapter(
        tmp_path,
        load,
        devices=[candidate("cuda:0"), candidate("cpu", "cpu")],
    )
    try:
        model._load()
    except LayaRuntimeUnavailable as exc:
        assert "cleanup" in str(exc).lower() or "close" in str(exc).lower()
    else:
        raise AssertionError("adapter must stop when failed-device cleanup is unconfirmed")
    assert attempts == ["cuda:0"]


def test_preloaded_router_cleanup_failure_stops_device_fallback(tmp_path, monkeypatch):
    routers = []

    class UncleanableRouter(FakeRouter):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._agents["unexpected-model"] = FakeAgent(kwargs["device"])

        def unload(self, name=None):
            raise OSError("preloaded provider cleanup failed")

    def make_router(**kwargs):
        router = UncleanableRouter(**kwargs)
        routers.append(router)
        return router

    fake_laya = type("FakeLaya", (), {"Router": staticmethod(make_router), "__version__": "fixture"})
    _patch_laya_runtime_imports(monkeypatch, fake_laya)
    model = adapter(tmp_path, None, devices=[candidate("cuda:0"), candidate("cpu", "cpu")])

    try:
        model._load()
    except LayaRuntimeUnavailable as exc:
        assert "cleanup" in str(exc).lower() or "close" in str(exc).lower()
    else:
        raise AssertionError("adapter must stop when preloaded Router cleanup is unconfirmed")
    assert len(routers) == 1


class FakeCapacityManager:
    def __init__(self, *, admitted=True, release_result=True, events=None):
        self.admitted = admitted
        self.release_result = release_result
        self.events = events if events is not None else []
        self.releases = []

    def acquire_gpu_capacity_lease(self, owner, requested_bytes):
        self.events.append(("acquire", owner, requested_bytes))
        if not self.admitted:
            return {"state": "rejected", "reason": "insufficient_capacity"}
        return {"state": "admitted", "lease_id": "lease-1", "generation": "generation-1"}

    def release_gpu_capacity_lease(self, lease_id, owner, generation):
        self.releases.append((lease_id, owner, generation))
        self.events.append(("release", lease_id, owner, generation))
        return self.release_result


def test_gpu_capacity_lease_spans_model_residency_until_confirmed_idle_unload(tmp_path):
    now = [0.0]
    events = []
    capacity = FakeCapacityManager(events=events)

    def load(_path, *, device, expected_sha256):
        events.append(("load", device))
        return FakeAgent(device)

    model = adapter(
        tmp_path, load, capacity_manager=capacity, capacity_request_bytes=2 * 1024**3
    )
    shared = LayaSessionLifecycle(
        600, close_session=model._close_with_capacity, clock=lambda: now[0]
    )
    request, evidence = request_and_evidence()

    result = model.evaluate_context_source(request, evidence, session_lifecycle=shared)

    assert result.decision.suggestion == "artifact"
    assert [item[0] for item in events] == ["acquire", "load"]
    assert capacity.releases == []
    assert shared.poll_idle_unload(now=now[0] + 599.999) == "not_idle"
    assert capacity.releases == []
    assert shared.poll_idle_unload(now=now[0] + 600) == "unloaded"
    assert len(capacity.releases) == 1
    lease_id, owner, generation = capacity.releases[0]
    assert (lease_id, generation) == ("lease-1", "generation-1")
    assert owner.startswith(f"laya-runtime:{os.getpid()}:")


def test_gpu_capacity_rejection_happens_before_provider_load(tmp_path):
    events = []
    capacity = FakeCapacityManager(admitted=False, events=events)

    def load(_path, *, device, expected_sha256):
        events.append(("load", device))
        return FakeAgent(device)

    model = adapter(
        tmp_path, load, capacity_manager=capacity, capacity_request_bytes=2 * 1024**3
    )
    request, evidence = request_and_evidence()

    result = model.evaluate_context_source(request, evidence, session_lifecycle=lifecycle())

    assert result.decision.status is DecisionStatus.ERROR
    assert events and events[0][0] == "acquire"
    assert not any(item[0] == "load" for item in events)
    assert capacity.releases == []


def test_failed_gpu_capacity_release_records_pending_after_confirmed_provider_unload(tmp_path):
    now = [0.0]
    capacity = FakeCapacityManager(release_result=False)
    model = adapter(
        tmp_path,
        lambda _path, *, device, expected_sha256: FakeAgent(device),
        capacity_manager=capacity,
        capacity_request_bytes=2 * 1024**3,
    )
    shared = LayaSessionLifecycle(1, close_session=model._close_with_capacity, clock=lambda: now[0])
    request, evidence = request_and_evidence()
    result = model.evaluate_context_source(request, evidence, session_lifecycle=shared)

    assert result.decision.suggestion == "artifact"
    assert shared.poll_idle_unload(now=2) == "unloaded"
    assert shared.status["available"] is False
    assert len(capacity.releases) == 1
    assert model._capacity_lease_release_pending is True


def test_laya_retries_pending_capacity_release_before_reacquiring(tmp_path):
    now = [0.0]
    capacity = FakeCapacityManager(release_result=False)
    model = adapter(
        tmp_path,
        lambda _path, *, device, expected_sha256: FakeAgent(device),
        capacity_manager=capacity,
        capacity_request_bytes=2 * 1024**3,
    )
    shared = LayaSessionLifecycle(1, close_session=model._close_with_capacity, clock=lambda: now[0])
    request, evidence = request_and_evidence()

    first = model.evaluate_context_source(request, evidence, session_lifecycle=shared)
    assert first.decision.suggestion == "artifact"
    assert shared.poll_idle_unload(now=2) == "unloaded"
    assert model._capacity_lease_release_pending is True

    capacity.release_result = True
    second = model.evaluate_context_source(request, evidence, session_lifecycle=shared)

    assert second.decision.suggestion == "artifact"
    assert [event[0] for event in capacity.events] == ["acquire", "release", "release", "acquire"]
    assert model._capacity_lease_release_pending is False
