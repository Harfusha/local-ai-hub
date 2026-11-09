import pytest

from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.hardware import choose_profile


def test_shared_model_uses_explicit_role_context():
    policy = ModelExecutionPolicy({
        "models": {"fast_code": "shared", "heavy_code": "shared", "reasoning": "shared", "vision": "shared"},
        "model_execution": {
            "fast": {"context_tokens": 8192},
            "smart": {"context_tokens": 16384},
            "vision": {"context_tokens": 32768},
        },
    })

    assert policy.profile("shared", role="fast_code").tier == "fast"
    assert policy.profile("shared", role="reasoning").num_ctx == 16384
    assert policy.profile("shared", role="review").tier == "smart"
    assert policy.profile("shared", role="second-opinion").tier == "smart"
    assert policy.profile("shared", role="vision", vram_free_mb=8192).num_ctx == 32768


def test_background_role_takes_precedence_over_shared_model():
    policy = ModelExecutionPolicy({"models": {"background_code": "shared", "vision": "shared"}})
    assert policy.profile("shared", role="background", background=True).tier == "background"


def test_review_of_fast_model_retains_fast_policy():
    policy = ModelExecutionPolicy({"models": {"fast_code": "fast", "heavy_code": "smart"}})
    assert policy.profile("fast", role="review").tier == "fast"


def test_16gib_gpu_selects_high_without_overriding_explicit_preference():
    gpu = [{"vram_mb": 16 * 1024, "integrated": False}]
    assert choose_profile(gpu, 32) == "high"
    assert choose_profile(gpu, 32, requested="balanced") == "balanced"


def test_configured_context_adapts_to_input_and_respects_ceiling_and_vram():
    policy = ModelExecutionPolicy({
        "models": {"reasoning": "qwen3.5:9b"},
        "model_execution": {"smart": {"context_tokens": 16384, "large_context_tokens": 32768,
                                       "max_context_tokens": 65536, "context_reserve_tokens": 2048}},
    })
    short = policy.profile("qwen3.5:9b", role="reasoning", input_tokens=1000, output_tokens=500)
    long = policy.profile("qwen3.5:9b", role="reasoning", input_tokens=15000, output_tokens=2000, vram_free_mb=8192)
    expanded = policy.profile("qwen3.5:9b", role="reasoning", requested_ctx=131072, vram_free_mb=16384)
    constrained = policy.profile("qwen3.5:9b", role="reasoning", requested_ctx=65536, vram_free_mb=4096)
    assert (short.num_ctx, long.num_ctx, expanded.num_ctx, constrained.num_ctx) == (16384, 32768, 65536, 8192)
    assert constrained.prompt_budget_tokens < constrained.num_ctx


def test_context_expands_to_fit_input_output_and_reserve_when_possible():
    policy = ModelExecutionPolicy({"models": {"reasoning": "model"}, "model_execution": {
        "smart": {"context_tokens": 8192, "large_context_tokens": 16384,
                  "max_context_tokens": 32768, "context_reserve_tokens": 2048}}})
    profile = policy.profile("model", role="reasoning", input_tokens=15000, output_tokens=4000, vram_free_mb=8192)
    assert profile.num_ctx == 32768
    assert profile.prompt_budget_tokens + 4000 + 2048 <= profile.num_ctx


def test_context_rejects_output_that_leaves_no_safe_prompt_budget():
    policy = ModelExecutionPolicy({"models": {"reasoning": "model"}, "model_execution": {
        "smart": {"context_tokens": 8192, "large_context_tokens": 8192,
                  "max_context_tokens": 8192, "context_reserve_tokens": 2048}}})
    with pytest.raises(ValueError, match="context.*output.*reserve"):
        policy.profile("model", role="reasoning", output_tokens=6000)
    payload = {"options": {"num_ctx": 8192}}
    with pytest.raises(ValueError, match="context.*output.*reserve"):
        policy.apply_payload("model", payload, role="reasoning", output_tokens=6000)
    assert payload == {"options": {"num_ctx": 8192}}


def test_generation_reserves_system_and_schema_before_fitting_prompt(monkeypatch):
    from local_ai_hub.budget import estimate_tokens
    from local_ai_hub.json_utils import dumps as json_dumps
    from local_ai_hub.services import LocalAIServices

    service = object.__new__(LocalAIServices)
    service.config = {}
    service.model_policy = ModelExecutionPolicy({"models": {"reasoning": "model"}, "model_execution": {
        "smart": {"context_tokens": 8192, "large_context_tokens": 8192,
                  "max_context_tokens": 8192, "context_reserve_tokens": 2048}}})
    service._available_vram_mb = lambda: None
    seen = {}
    def capture(_model, payload, **kwargs):
        seen.update(payload=payload, kwargs=kwargs)
        raise RuntimeError("captured before inference")
    monkeypatch.setattr(service.model_policy, "apply_payload", capture)
    system = "system " * 1000
    schema = {"type": "object", "description": "schema " * 200}
    with pytest.raises(RuntimeError, match="captured before inference"):
        service._generate("model", "evidence " * 5000, system, 512, 0.2,
                          source="reason:reasoning", priority=1, format=schema)
    used = (estimate_tokens(seen["payload"]["prompt"]) + estimate_tokens(system)
            + estimate_tokens(json_dumps(schema, ensure_ascii=False)))
    assert used + 512 + 2048 <= 8192
    assert seen["kwargs"]["input_tokens"] == used
    seen.clear()
    with pytest.raises(ValueError, match="context cannot fit the system prompt"):
        service._generate("model", "request", "system " * 5000, 512, 0.2,
                          source="reason:reasoning", priority=1)
    assert not seen


def test_background_generation_reserves_system_and_schema(monkeypatch):
    import json
    from local_ai_hub.background_gpu import IdleGPUWorker
    from local_ai_hub.budget import estimate_tokens

    worker = object.__new__(IdleGPUWorker)
    worker.model = "model"
    worker.runtime = object()
    worker._bg_config = {}
    worker.policy = ModelExecutionPolicy({"model_execution": {"background": {
        "context_tokens": 8192, "background_context_tokens": 8192,
        "large_context_tokens": 8192, "max_context_tokens": 8192, "context_reserve_tokens": 2048}}})
    captured = {}
    def capture(_model, payload, **kwargs):
        captured.update(payload=payload, kwargs=kwargs)
        raise RuntimeError("captured before inference")
    monkeypatch.setattr(worker.policy, "apply_payload", capture)
    system = "system " * 1000
    schema = {"type": "object", "description": "schema " * 200}
    with pytest.raises(RuntimeError, match="captured before inference"):
        worker._generate_one({"prompt": "evidence " * 5000, "system": system,
                              "schema": schema, "max_tokens": 512}, preemptible=False)
    used = (estimate_tokens(captured["payload"]["prompt"]) + estimate_tokens(system)
            + estimate_tokens(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))))
    assert used + 512 + 2048 <= 8192
    assert captured["kwargs"]["input_tokens"] == used
    captured.clear()
    result = worker._generate_one({"prompt": "request", "system": "system " * 5000,
                                   "max_tokens": 512}, preemptible=False)
    assert result["success"] is False
    assert "context cannot fit" in result["error"]
    assert not captured


def test_preprocess_fallback_reserves_system_and_schema(monkeypatch):
    from types import SimpleNamespace
    from local_ai_hub.budget import estimate_tokens
    from local_ai_hub.json_utils import dumps as json_dumps
    from local_ai_hub.preprocess import ProjectPreprocessor

    worker = object.__new__(ProjectPreprocessor)
    worker.config = {}
    worker.cfg = {}
    worker.state_dir = None
    worker.background_gpu = None
    worker._gpu_yield = lambda: False
    worker.scheduler = SimpleNamespace(submit=lambda _model, **kwargs: kwargs["execute"]())
    policy = ModelExecutionPolicy({"model_execution": {"background": {
        "context_tokens": 8192, "background_context_tokens": 8192,
        "large_context_tokens": 8192, "max_context_tokens": 8192, "context_reserve_tokens": 2048}}})
    worker.services = SimpleNamespace(model_policy=policy)
    original_apply = policy.apply_payload
    captured = {}
    def capture(_model, payload, **kwargs):
        captured.update(payload=payload, kwargs=kwargs)
        raise RuntimeError("captured before inference")
    monkeypatch.setattr(policy, "apply_payload", capture)
    system = "system " * 1000
    schema = {"type": "object", "description": "schema " * 200}
    with pytest.raises(RuntimeError, match="captured before inference"):
        worker._run_background_generate("model", "evidence " * 5000, system, schema, 512, "preprocess:test")
    used = (estimate_tokens(captured["payload"]["prompt"]) + estimate_tokens(system)
            + estimate_tokens(json_dumps(schema, ensure_ascii=False)))
    assert used + 512 + 2048 <= 8192
    assert captured["kwargs"]["input_tokens"] == used
    monkeypatch.setattr(policy, "apply_payload", original_apply)
    worker.scheduler.foreground_busy = lambda: False
    worker.runtime = SimpleNamespace(request_interruptible=lambda *_args, **_kwargs: {"response": '{"purpose":"x"}'})
    result = worker._run_background_generate("model", "evidence " * 5000, system, schema, 512, "preprocess:test")
    assert result["success"] is True
    assert result["prompt_budget"]["truncated"] is True


@pytest.mark.parametrize("prompt,truncated", [("short task", False), ("evidence " * 5000, True)], ids=["complete", "truncated"])
def test_background_generation_reports_prompt_truncation(monkeypatch, prompt, truncated):
    from types import SimpleNamespace
    from local_ai_hub.background_gpu import IdleGPUWorker
    from local_ai_hub import operational_mode

    worker = object.__new__(IdleGPUWorker)
    worker.model = "model"
    worker.config = {"server": {"state_dir": "unused"}}
    worker._bg_config = {}
    worker.request_timeout = 1
    worker.runtime = SimpleNamespace(request_interruptible=lambda *_args, **_kwargs: {"response": '{"purpose":"x"}'})
    worker.policy = ModelExecutionPolicy({"model_execution": {"background": {
        "context_tokens": 8192, "background_context_tokens": 8192,
        "large_context_tokens": 8192, "max_context_tokens": 8192}}})
    monkeypatch.setattr(operational_mode, "load_operational_mode", lambda _state: SimpleNamespace(degraded=False, mode="active"))
    result = worker._generate_one({"prompt": prompt, "system": "system", "max_tokens": 512}, preemptible=False)
    assert result["success"] is True
    assert result["prompt_budget"]["truncated"] is truncated
    assert result["prompt_budget"]["estimated_tokens"] <= result["prompt_budget"]["original_estimated_tokens"]


def test_preprocessing_card_preserves_only_trusted_prompt_budget():
    from local_ai_hub.preprocess import ProjectPreprocessor

    forged = {"purpose": "summary", "_input_prompt_budget": {"truncated": False}}
    budget = {"truncated": True, "estimated_tokens": 100, "original_estimated_tokens": 200}
    card = ProjectPreprocessor._generated_card_data({"data": forged, "prompt_budget": budget})
    assert card["_input_prompt_budget"] == budget
    assert forged["_input_prompt_budget"] == {"truncated": False}
    assert "_input_prompt_budget" not in ProjectPreprocessor._generated_card_data({"data": forged})
    assert "_input_prompt_budget" not in ProjectPreprocessor._generated_card_data(
        {"data": forged, "prompt_budget": {**budget, "truncated": "false"}})
