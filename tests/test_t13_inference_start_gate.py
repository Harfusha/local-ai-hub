from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub.background_gpu import IdleGPUWorker
from local_ai_hub.operational_mode import set_operational_mode
from local_ai_hub.preprocess import ProjectPreprocessor


class _Policy:
    def profile(self, *_args, **_kwargs):
        return SimpleNamespace(prompt_budget_tokens=4096)

    def apply_payload(self, _model, payload, **_kwargs):
        return payload, object()


class _Runtime:
    def __init__(self):
        self.calls = 0

    def request_interruptible(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("paused background inference reached runtime")


def test_queued_preprocess_rechecks_mode_before_runtime_start(tmp_path):
    state_dir = tmp_path / "state"
    set_operational_mode(state_dir, "active")
    runtime = _Runtime()

    class _Scheduler:
        def submit(self, _model, _tenant, _source, execute, **_kwargs):
            set_operational_mode(state_dir, "gaming")
            return execute()

    pre = object.__new__(ProjectPreprocessor)
    pre._gpu_yield = lambda: False
    pre.background_gpu = None
    pre.services = type("Services", (), {"model_policy": _Policy()})()
    pre.config = {"server": {"state_dir": str(state_dir)}, "ollama": {}}
    pre.runtime = runtime
    pre.cfg = {"background_scheduler_timeout_seconds": 1}
    pre.scheduler = _Scheduler()

    result = pre._run_background_generate("small", "prompt", "system", {}, 32, "preprocess:test")

    assert result["error_code"] == "operational_mode_paused"
    assert runtime.calls == 0


def test_queued_gpu_worker_rechecks_mode_before_runtime_start(tmp_path):
    state_dir = tmp_path / "state"
    set_operational_mode(state_dir, "gaming")
    runtime = _Runtime()
    worker = object.__new__(IdleGPUWorker)
    worker.config = {"server": {"state_dir": str(state_dir)}}
    worker.model = "small"
    worker.request_timeout = 1
    worker._bg_config = {}
    worker.runtime = runtime
    worker.policy = _Policy()
    worker._foreground_requested = lambda: False

    result = worker._generate_one({"prompt": "prompt", "system": "system"}, preemptible=False)

    assert result["error_code"] == "operational_mode_paused"
    assert runtime.calls == 0
