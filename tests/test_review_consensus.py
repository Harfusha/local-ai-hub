from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.router import ModelRouter
from local_ai_hub.services import LocalAIServices


def configure_review_routing(services):
    config = {
        "models": {
            "fast_code": "qwen2.5-coder:3b-instruct-q5_K_M",
            "heavy_code": "qwen2.5-coder:7b-instruct-q5_K_M",
            "reasoning": "qwen2.5-coder:7b-instruct-q5_K_M",
            "general": "qwen2.5-coder:3b-instruct-q5_K_M",
        },
        "routing": {"prefer_resident_model": False},
        "token_saving": {"max_local_input_tokens": 56000},
    }
    services.config = config
    services.router = ModelRouter(config)
    services.model_policy = ModelExecutionPolicy(config)
    services._resident_optimize = lambda route, task_type, complexity: route
    services.vram_balancer = None


def test_review_diff_consensus_explicit():
    services = MagicMock(spec=LocalAIServices)
    configure_review_routing(services)
    services.deterministic = MagicMock()
    services.deterministic.diff_facts.return_value = {
        "deterministic": True,
        "breaking_changes": [],
        "risk_level": "low",
    }
    services.repo_diff.return_value = {
        "success": True,
        "diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n",
        "changed_files": ["file.py"],
        "truncated": False,
        "estimated_tokens": 10,
        "original_estimated_tokens": 10,
    }

    # Callbacks for primary and secondary delegate calls
    delegate_calls = []
    def fake_delegate(payload, tenant):
        delegate_calls.append(payload)
        if payload.get("task_type") == "reasoning":
            return {"success": True, "text": "Secondary review: looks fine.", "model": "qwen3.5:9b"}
        return {"success": True, "text": "Primary review: bug found.", "model": "qwen2.5-coder:7b"}

    services.delegate = fake_delegate

    # Call actual unbound review_diff
    res = LocalAIServices.review_diff(services, {"root": ".", "consensus": True}, "test_tenant")
    assert res["success"] is True
    assert "consensus" in res
    assert res["consensus"]["enabled"] is True
    assert res["consensus"]["triggered_by"] == "explicit"
    assert "Primary review" in res["text"]
    assert "Secondary review" in res["text"]
    assert len(delegate_calls) == 2


def test_review_diff_auto_consensus_on_breaking_changes():
    services = MagicMock(spec=LocalAIServices)
    configure_review_routing(services)
    services.deterministic = MagicMock()
    services.deterministic.diff_facts.return_value = {
        "deterministic": True,
        "breaking_changes": [{"symbol": "foo", "type": "removed_symbol", "file": "api.py", "description": "removed"}],
        "risk_level": "high",
    }
    services.repo_diff.return_value = {
        "success": True,
        "diff": "--- a/api.py\n+++ b/api.py\n@@ -1 +1 @@\n-def foo(): pass\n",
        "changed_files": ["api.py"],
        "truncated": False,
        "estimated_tokens": 10,
        "original_estimated_tokens": 10,
    }

    delegate_calls = []
    def fake_delegate(payload, tenant):
        delegate_calls.append(payload)
        return {"success": True, "text": "Audited.", "model": "model_x"}

    services.delegate = fake_delegate

    # Without explicit consensus flag, breaking_changes should auto-trigger consensus
    res = LocalAIServices.review_diff(services, {"root": "."}, "test_tenant")
    assert res["success"] is True
    assert "consensus" in res
    assert res["consensus"]["enabled"] is True
    assert res["consensus"]["triggered_by"] == "breaking_changes"
    assert len(delegate_calls) == 2
