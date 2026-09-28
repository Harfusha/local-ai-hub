from __future__ import annotations

import pytest


def _router():
    from local_ai_hub.router import ModelRouter

    return ModelRouter({
        "models": {"fast_code": "fast", "heavy_code": "smart", "reasoning": "smart", "general": "fast"},
        "routing": {
            "heavy_min_score": 3,
            "review_heavy_min_score": 5,
            "complex_terms": ["one", "two", "tri"],
        },
    })


def test_review_score_four_stays_on_fast_model():
    route = _router().classify("review one two tri\n" * 161)

    assert route["task_type"] == "review"
    assert route["complexity_score"] == 4
    assert route["model"] == "fast"


def test_review_score_five_uses_smart_model():
    route = _router().classify("review one two tri\n" * 161 + "```\n" + "def\n" * 8)

    assert route["task_type"] == "review"
    assert route["complexity_score"] == 5
    assert route["model"] == "smart"


def test_reasoning_uses_basic_qwen_until_complexity_requires_smart_model():
    from local_ai_hub.router import ModelRouter

    router = ModelRouter({
        "models": {
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
        },
        "routing": {"heavy_min_score": 3},
    })

    basic = router.classify("Why does this function fail?", task_type="reasoning")
    complex_task = router.classify(
        "Analyze architecture concurrency deadlock migration rollback protocol",
        task_type="reasoning",
    )

    assert basic["model"] == "qwen2.5-coder:3b"
    assert complex_task["model"] == "qwen2.5-coder:7b"


def test_balanced_profile_reserves_9b_for_extreme_reasoning():
    from local_ai_hub.router import ModelRouter

    router = ModelRouter({
        "models": {
            "fast_code": "qwen2.5-coder:7b",
            "heavy_code": "qwen2.5-coder:7b",
            "reasoning": "qwen3.5:9b",
            "general": "qwen2.5-coder:7b",
        },
        "routing": {"heavy_min_score": 3},
    })

    ordinary = router.classify("Explain this failure", task_type="reasoning", complexity="fast")
    extreme = router.classify("Analyze the root cause across modules", task_type="reasoning", complexity="heavy")

    assert ordinary["model"] == "qwen2.5-coder:7b"
    assert extreme["model"] == "qwen3.5:9b"


def test_heavy_review_cannot_be_downgraded_below_configured_quality_floor():
    router = _router()
    route = router.classify("review one two tri\n" * 161 + "```\n" + "def\n" * 8)

    assert route["complexity"] == "heavy"
    with pytest.raises(ValueError, match="quality floor"):
        router.apply_model_override(route, "fast")


@pytest.mark.parametrize("profile", ["integrated", "balanced", "high", "max"])
def test_hardware_profiles_keep_heavy_review_above_fast_tier(profile):
    from local_ai_hub.hardware import PROFILE_OVERRIDES
    from local_ai_hub.router import ModelRouter

    models = PROFILE_OVERRIDES[profile]["models"]
    router = ModelRouter({"models": models})
    route = router.classify("review", task_type="review", complexity="heavy")

    assert route["model"] == models["heavy_code"]
    with pytest.raises(ValueError, match="quality floor"):
        router.apply_model_override(route, models["fast_code"])


@pytest.mark.parametrize("profile", ["integrated", "balanced", "high"])
def test_reasoning_profiles_reject_override_below_reasoning_tier(profile):
    from local_ai_hub.hardware import PROFILE_OVERRIDES
    from local_ai_hub.router import ModelRouter

    models = PROFILE_OVERRIDES[profile]["models"]
    router = ModelRouter({"models": models})
    route = router.classify("Analyze root cause", task_type="reasoning", complexity="heavy")

    assert models["reasoning"] != models["heavy_code"]
    assert route["model"] == models["reasoning"]
    with pytest.raises(ValueError, match="quality floor"):
        router.apply_model_override(route, models["heavy_code"])


@pytest.mark.parametrize(
    ("profile", "gpus", "ram_gb", "expected_heavy", "expected_reasoning"),
    [
        ("integrated", [{"integrated": True, "vendor": "intel"}], 16, "qwen2.5-coder:3b", "qwen2.5-coder:7b"),
        ("balanced", [{"integrated": False, "vram_mb": 8 * 1024}], 16, "qwen2.5-coder:7b", "qwen3.5:9b"),
        ("high", [{"integrated": False, "vram_mb": 12 * 1024}], 16, "qwen2.5-coder:7b", "qwen3.5:9b"),
        ("max", [{"integrated": False, "vram_mb": 20 * 1024}], 16, "qwen3.5:9b", "qwen3.5:9b"),
    ],
)
def test_detected_hardware_profile_feeds_profile_models_to_router(
    profile, gpus, ram_gb, expected_heavy, expected_reasoning
):
    from local_ai_hub.hardware import choose_profile, profile_overrides
    from local_ai_hub.router import ModelRouter

    selected = choose_profile(gpus, ram_gb)
    models = profile_overrides(selected)["models"]
    router = ModelRouter({"models": models})

    assert selected == profile
    review = router.classify("review", task_type="review", complexity="heavy")
    reasoning = router.classify("analyze root cause", task_type="reasoning", complexity="heavy")
    assert models["heavy_code"] == expected_heavy
    assert models["reasoning"] == expected_reasoning
    assert review["model"] == expected_heavy
    assert reasoning["model"] == expected_reasoning


def test_second_opinion_uses_basic_qwen_by_default():
    from local_ai_hub.router import ModelRouter
    from local_ai_hub.services import LocalAIServices

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {
        "models": {
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
            "reasoning": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:1.5b",
        },
        "routing": {"heavy_min_score": 3},
    }
    service.router = ModelRouter(service.config)
    service._generate = lambda model, *args, **kwargs: {"success": True, "model": model}

    result = service.second_opinion(
        {"question": "Why does this function fail?", "candidate": "It has a bug."},
        "test-tenant",
    )

    assert result["model"] == "qwen2.5-coder:3b"


def test_semantic_language_marks_local_inference_as_required():
    route = _router().classify("Explore the relevant behavior and explain alternatives")

    assert route["task_type"] == "reasoning"
    assert route["semantic_required"] is True


def test_explicit_reasoning_cannot_be_short_circuited_by_exact_evidence():
    route = _router().classify("Why does this behavior happen?", task_type="reasoning")

    assert route["semantic_required"] is True


def test_repository_context_does_not_fake_a_semantic_user_intent():
    route = _router().classify("Find the exact symbol", context="comment: explain alternatives")

    assert route["semantic_required"] is False


@pytest.mark.parametrize("profile", ["cpu", "low"])
def test_cpu_and_low_profiles_keep_integrated_model_role_map(profile):
    from local_ai_hub.hardware import PROFILE_OVERRIDES

    assert PROFILE_OVERRIDES[profile]["models"] == PROFILE_OVERRIDES["integrated"]["models"]
