from __future__ import annotations


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
            "fast_code": "qwen2.5-coder:7b",
            "heavy_code": "qwen3.5:9b",
            "reasoning": "qwen3.5:9b",
            "general": "qwen2.5-coder:7b",
        },
        "routing": {"heavy_min_score": 3},
    })

    basic = router.classify("Why does this function fail?", task_type="reasoning")
    complex_task = router.classify(
        "Analyze architecture concurrency deadlock migration rollback protocol",
        task_type="reasoning",
    )

    assert basic["model"] == "qwen2.5-coder:7b"
    assert complex_task["model"] == "qwen3.5:9b"


def test_second_opinion_uses_basic_qwen_by_default():
    from local_ai_hub.router import ModelRouter
    from local_ai_hub.services import LocalAIServices

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {
        "models": {
            "fast_code": "qwen2.5-coder:7b",
            "heavy_code": "qwen3.5:9b",
            "reasoning": "qwen3.5:9b",
            "general": "qwen2.5-coder:7b",
        },
        "routing": {"heavy_min_score": 3},
    }
    service.router = ModelRouter(service.config)
    service._generate = lambda model, *args, **kwargs: {"success": True, "model": model}

    result = service.second_opinion(
        {"question": "Why does this function fail?", "candidate": "It has a bug."},
        "test-tenant",
    )

    assert result["model"] == "qwen2.5-coder:7b"
