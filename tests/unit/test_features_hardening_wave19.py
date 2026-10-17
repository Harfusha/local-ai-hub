import pytest
from local_ai_hub.features import FeatureSet, rollout_feature_enabled


def test_rollout_feature_enabled_hardening():
    assert not rollout_feature_enabled(True, "enriched_search")
    assert not rollout_feature_enabled(None, "enriched_search")
    assert not rollout_feature_enabled({"features": {"enriched_search": True}}, True)
    assert not rollout_feature_enabled({"features": {"enriched_search": True}}, 123)
    assert not rollout_feature_enabled({"features": {"enriched_search": 1}}, "enriched_search")
    assert rollout_feature_enabled({"features": {"enriched_search": True}}, "enriched_search")


def test_featureset_profiles_and_models_hardening():
    # The canonical TOML shape is a profile table; list expansion is not supported.
    cfg_profiles = {
        "ollama_subagents": {
            "profiles": {"agent-a": {}, "agent-b": {}}
        }
    }
    fs_profiles = FeatureSet(cfg_profiles)
    assert "agent-a" in fs_profiles.subagent_profiles
    assert "agent-b" in fs_profiles.subagent_profiles

    fs_list = FeatureSet({"ollama_subagents": {"profiles": ["agent-a", "agent-b"]}})
    assert fs_list.subagent_profiles == ("qwen-explorer", "qwen-drafter", "qwen-critic")

    # profiles as boolean or invalid type should fall back cleanly
    cfg_bool = {
        "ollama_subagents": {
            "profiles": True
        }
    }
    fs_bool = FeatureSet(cfg_bool)
    assert "qwen-explorer" in fs_bool.subagent_profiles

    # Explicit None in models should not produce literal string "None"
    cfg_none_models = {
        "models": {
            "fast_code": None,
            "heavy_code": None,
            "reasoning": None,
            "background_code": None,
            "embedding": None,
            "reranker": None,
        }
    }
    fs_models = FeatureSet(cfg_none_models)
    assert fs_models.fast_model != "None"
    assert fs_models.smart_model != "None"
    assert fs_models.reasoning_model != "None"
    assert fs_models.background_model != "None"
    assert fs_models.embedding_model != "None"
    assert fs_models.reranker_model != "None"

    fs_malformed_model = FeatureSet({"models": {"fast_code": 123}})
    assert fs_malformed_model.fast_model == "qwen2.5-coder:1.5b"

    fs_malformed_profile = FeatureSet({"ollama_subagents": {"profiles": {1: {}}}})
    assert "1" not in fs_malformed_profile.subagent_profiles
