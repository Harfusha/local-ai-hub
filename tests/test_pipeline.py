from local_ai_hub.pipeline import LocalAgentPipeline


def test_repo_worker_uses_basic_qwen_for_ordinary_adaptive_tasks():
    route = {"complexity": "fast", "complexity_score": 1}
    assert LocalAgentPipeline._select_worker_model(route, "adaptive", 0, 4, "qwen2.5-coder:1.5b", "qwen2.5-coder:3b") == "qwen2.5-coder:1.5b"


def test_repo_worker_escalates_smart_for_explicit_quality_or_risk():
    fast = {"complexity": "fast", "complexity_score": 1}
    heavy = {"complexity": "heavy", "complexity_score": 3}
    assert LocalAgentPipeline._select_worker_model(fast, "quality", 0, 4, "fast", "smart") == "smart"
    assert LocalAgentPipeline._select_worker_model(heavy, "adaptive", 0, 4, "fast", "smart") == "smart"
    assert LocalAgentPipeline._select_worker_model(fast, "adaptive", 4, 4, "fast", "smart") == "smart"


def test_repo_critic_keeps_ordinary_review_on_basic_qwen():
    review = {"complexity": "fast", "complexity_score": 1}
    assert LocalAgentPipeline._select_worker_model(review, "adaptive", 1, 4, "qwen2.5-coder:1.5b", "qwen2.5-coder:3b") == "qwen2.5-coder:1.5b"


def test_pipeline_initialization_has_max_final_chars(tmp_path):
    cfg = {
        "server": {"state_dir": str(tmp_path)},
        "local_pipeline": {"max_final_chars": 2500},
        "token_saving": {"max_inline_chars": 1800},
    }
    p = LocalAgentPipeline(cfg, None, None)
    assert p.max_final_chars == 2500

    cfg_fallback = {
        "server": {"state_dir": str(tmp_path)},
        "token_saving": {"max_inline_chars": 1800},
    }
    p2 = LocalAgentPipeline(cfg_fallback, None, None)
    assert p2.max_final_chars == 1800

