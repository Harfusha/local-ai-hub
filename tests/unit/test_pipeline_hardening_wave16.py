import pytest
from local_ai_hub.pipeline import LocalAgentPipeline


class DummyServices:
    def __init__(self):
        self.router = None
        self.deterministic = None
        self.code_index = None


def test_pipeline_init_safe_config_values(tmp_path):
    # Config with None values in local_pipeline must not raise TypeError or OverflowError
    config = {
        "server": {"state_dir": str(tmp_path)},
        "local_pipeline": {
            "enabled": True,
            "critic_min_risk_score": None,
            "critic_min_complexity_score": True,
            "worker_min_complexity_score": "not_an_int",
            "explorer_max_tokens": None,
            "worker_max_tokens": float("inf"),
            "critic_max_tokens": float("-inf"),
            "same_model_worker_passes": None,
            "second_pass_min_complexity_score": "bad",
            "explorer_skip_worker_confidence": None,
            "direct_smart_complexity_score": None,
            "direct_smart_risk_score": None,
            "max_final_chars": None,
            "ttl_seconds": None,
            "max_entries": None,
            "l1_entries": None,
            "l1_ttl_seconds": None,
        },
        "resilience": {
            "singleflight_wait_timeout_seconds": None,
        },
    }
    pipeline = LocalAgentPipeline(config, DummyServices(), None)
    assert pipeline.critic_risk_score == 4
    assert pipeline.critic_min_complexity_score == 3
    assert pipeline.worker_complexity_score == 2
    assert pipeline.max_explorer_tokens == 650
    assert pipeline.max_worker_tokens == 1300
    assert pipeline.max_critic_tokens == 750


def test_pipeline_init_missing_server_state_dir(tmp_path):
    # Config without server or state_dir must not raise KeyError / TypeError
    config = {
        "local_pipeline": {"enabled": True},
    }
    pipeline = LocalAgentPipeline(config, DummyServices(), None)
    assert pipeline.cache is not None


def test_select_worker_model_invalid_inputs():
    # Non-dict route or route with invalid complexity_score
    res = LocalAgentPipeline._select_worker_model(None, "adaptive", 0, 99, "fast", "heavy")
    assert res == "fast"

    res2 = LocalAgentPipeline._select_worker_model({"complexity_score": "invalid"}, "adaptive", 0, 99, "fast", "heavy")
    assert res2 == "fast"

    res3 = LocalAgentPipeline._select_worker_model({"complexity_score": float("inf")}, "adaptive", 0, 99, "fast", "heavy")
    assert res3 == "fast"
