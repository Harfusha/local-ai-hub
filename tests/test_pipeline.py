from local_ai_hub.pipeline import (
    LocalAgentPipeline,
    _queue_laya_context_budget_shadow,
    _queue_laya_delegation_shadow,
)


class _LayaShadowQueue:
    def __init__(self):
        self.calls = []

    def _queue_laya_shadow_observation(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return True


def test_pipeline_queues_context_budget_shadow_for_scoped_automatic_budget():
    queue = _LayaShadowQueue()
    args = {"task_id": "task-123", "context_tokens": 0}
    packed = {
        "success": True,
        "context_source": "deterministic",
        "evidence": [
            {"evidence_id": {"invalid": "shape"}, "text": "UNVERIFIED_SOURCE_TEXT"},
            {
                "evidence_id": "evidence-1",
                "text": "RETRIEVED_SOURCE_EXCERPT",
                "content": "UNSELECTED_SOURCE_CONTENT",
            },
        ],
    }

    queued = _queue_laya_context_budget_shadow(
        queue,
        args,
        root="C:/repo",
        task="Explain the bounded repository context.",
        route={"complexity": "heavy"},
        risk_score=0.25,
        budget=4200,
        packed=packed,
        deterministic={"evidence": []},
        preliminary={"confidence": 0.72},
        response={"success": True, "text": "The worker answer uses the retrieved repository context."},
    )

    assert queued is True
    assert len(queue.calls) == 1
    observed_args, operation = queue.calls[0]
    assert observed_args["task_id"] == "task-123"
    assert observed_args["evidence_ids"] == ["evidence-1"]
    assert operation["root"] == "C:/repo"
    assert operation["category"] == "context_budget"
    assert operation["options"] == ["compact", "standard", "expanded"]
    assert operation["baseline"] == {
        "method": "repo_context_token_budget",
        "suggestion": "expanded",
        "evidence_id": "evidence-1",
    }
    assert operation["training_content"] == {
        "task_input": "Explain the bounded repository context.",
        "model_response": "The worker answer uses the retrieved repository context.",
        "context_excerpt": "RETRIEVED_SOURCE_EXCERPT",
    }
    assert "UNSELECTED_SOURCE_CONTENT" not in repr(queue.calls)
    assert "UNVERIFIED_SOURCE_TEXT" not in repr(queue.calls)


def test_pipeline_bounds_context_budget_training_content():
    queue = _LayaShadowQueue()
    evidence_text = "x" * (8 * 1024)
    queued = _queue_laya_context_budget_shadow(
        queue,
        {"task_id": "task-123", "context_tokens": 0},
        root="C:/repo",
        task="Explain this repository context.",
        route={"complexity": "fast"},
        risk_score=0.0,
        budget=2200,
        packed={"success": True, "evidence": [{"evidence_id": "evidence-1", "text": evidence_text}]},
        deterministic={"evidence": []},
        preliminary={"confidence": 0.72},
        response={"success": True, "text": "The bounded worker answer."},
    )

    assert queued is True
    training_content = queue.calls[0][1]["training_content"]
    assert len(training_content["context_excerpt"].encode("utf-8")) <= 6 * 1024
    assert sum(len(value.encode("utf-8")) for value in training_content.values()) <= 16 * 1024


def test_pipeline_skips_context_budget_shadow_for_explicit_or_unscoped_input():
    queue = _LayaShadowQueue()
    common = {
        "root": "C:/repo",
        "task": "Explain the bounded repository context.",
        "route": {"complexity": "fast"},
        "risk_score": 0.0,
        "budget": 900,
        "packed": {"success": True, "evidence": [{"evidence_id": "evidence-1"}]},
        "deterministic": {"evidence": []},
        "preliminary": {"confidence": 0.95},
        "response": {"success": True, "text": "response"},
    }

    assert _queue_laya_context_budget_shadow(
        queue, {"task_id": "task-123", "context_tokens": 1200}, **common
    ) is False
    assert _queue_laya_context_budget_shadow(
        queue, {"context_tokens": 0}, **common
    ) is False
    assert _queue_laya_context_budget_shadow(
        queue, {"task_id": "task-123", "context_tokens": 0}, **{
            **common,
            "packed": {"success": True, "evidence": []},
        }
    ) is False
    assert queue.calls == []


def test_pipeline_skips_context_budget_shadow_when_delegated_response_failed():
    queue = _LayaShadowQueue()
    assert _queue_laya_context_budget_shadow(
        queue,
        {"task_id": "task-123", "context_tokens": 0},
        root="C:/repo",
        task="Explain the bounded repository context.",
        route={"complexity": "fast"},
        risk_score=0.0,
        budget=900,
        packed={"success": True, "evidence": [{"evidence_id": "evidence-1"}]},
        deterministic={"evidence": []},
        preliminary={"confidence": 0.95},
        response={"success": False, "text": "partial output"},
    ) is False
    assert queue.calls == []


def test_pipeline_queues_delegation_shadow_for_grounded_worker_gate():
    queue = _LayaShadowQueue()
    queued = _queue_laya_delegation_shadow(
        queue,
        {"task_id": "task-123"},
        root="C:/repo",
        task="Find the implementation path for this request.",
        mode="adaptive",
        route={"complexity": "moderate", "task_type": "code"},
        risk_score=1.5,
        plan={"worker": False, "reason": "7b-confidence-sufficient"},
        need_worker=False,
        explorer={
            "success": True,
            "structured": {
                "confidence": 0.97,
                "missing_evidence": [],
                "evidence_ids": ["evidence-1"],
                "summary": "Grounded scout found the implementation path.",
            },
        },
        packed={
            "success": True,
            "evidence": [{"evidence_id": "evidence-1", "text": "Verified source excerpt."}],
        },
        response={"success": True, "text": "The grounded scout result."},
    )

    assert queued is True
    assert len(queue.calls) == 1
    observed_args, operation = queue.calls[0]
    assert observed_args["task_id"] == "task-123"
    assert observed_args["evidence_ids"] == ["evidence-1"]
    assert operation["root"] == "C:/repo"
    assert operation["category"] == "delegation"
    assert operation["options"] == ["delegate_bounded", "no_delegation"]
    assert operation["baseline"] == {
        "method": "pipeline_worker_escalation",
        "suggestion": "no_delegation",
        "evidence_id": "evidence-1",
    }
    assert operation["training_content"] == {
        "task_input": "Find the implementation path for this request.",
        "context_excerpt": "Grounded scout found the implementation path.",
        "model_response": "The grounded scout result.",
    }


def test_pipeline_delegation_shadow_requires_successful_scoped_evidence():
    queue = _LayaShadowQueue()
    common = {
        "root": "C:/repo",
        "task": "Find the implementation path.",
        "mode": "adaptive",
        "route": {"complexity": "fast", "task_type": "code"},
        "risk_score": 0.0,
        "plan": {"worker": True},
        "need_worker": True,
        "explorer": {"success": True, "structured": {"summary": "Scout"}},
        "packed": {"success": True, "evidence": [{"evidence_id": "evidence-1", "text": "source"}]},
        "response": {"success": True, "text": "result"},
    }

    assert _queue_laya_delegation_shadow(queue, {"task_id": "task-123"}, **{
        **common,
        "response": {"success": False, "text": "partial"},
    }) is False
    assert _queue_laya_delegation_shadow(queue, {"task_id": "task-123"}, **{
        **common,
        "packed": {"success": True, "evidence": []},
    }) is False
    assert _queue_laya_delegation_shadow(queue, {}, **common) is False
    assert queue.calls == []


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

