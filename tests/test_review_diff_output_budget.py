from types import SimpleNamespace

from local_ai_hub import services as services_module
from local_ai_hub.services import LocalAIServices


def test_chunked_review_uses_available_synthesis_output_budget(monkeypatch):
    monkeypatch.setattr(services_module, "_REVIEW_SYNTHESIS_CONTEXT_TOKENS", 4096)
    monkeypatch.setattr(services_module, "_REVIEW_DIFF_CONTEXT_FRACTION", 0.15)
    payloads = []

    def delegate(payload, **_kwargs):
        payloads.append(payload)
        return {
            "success": True,
            "model": "fast-model",
            "text": 'SUMMARY: No actionable defects found.\n```json\n{"verdict":"pass","findings":[]}\n```',
        }

    service = SimpleNamespace(
        config={},
        deterministic=None,
        incident_store=None,
        router=SimpleNamespace(classify=lambda *_args: {"model": "fast-model", "complexity": "fast"}),
        _resident_optimize=lambda route, *_args: route,
        model_policy=SimpleNamespace(
            tier_for=lambda _model: "fast",
            profile=lambda *_args, **_kwargs: SimpleNamespace(prompt_budget_tokens=32000),
        ),
        vram_balancer=None,
        delegate=delegate,
    )
    sections = []
    for filename in ("first.py", "second.py"):
        removed = "".join(f"-old_{index}_{'x' * 110}\n" for index in range(80))
        added = "".join(f"+new_{index}_{'y' * 110}\n" for index in range(80))
        sections.append(
            f"diff --git a/{filename} b/{filename}\n"
            f"--- a/{filename}\n+++ b/{filename}\n"
            f"@@ -1,80 +1,80 @@\n{removed}{added}"
        )

    result = LocalAIServices.review_diff(
        service,
        {"diff": "".join(sections), "max_tokens": 4096},
    )

    review_budgets = [payload["max_tokens"] for payload in payloads if payload.get("operation") == "review_diff"]
    assert result["success"] is True
    assert len(review_budgets) >= 2
    assert min(review_budgets) > 700


def test_truncated_review_segment_is_resegmented_without_replaying_same_input():
    payloads = []

    def delegate(payload):
        payloads.append(payload)
        if payload.get("task", "").startswith("SYNTHESIZE REVIEW FINDINGS ONLY."):
            return {"success": True, "model": "fast-model", "text": "SUMMARY: Review complete."}
        if sum(item.get("operation") == "review_diff" for item in payloads) == 1:
            return {
                "success": False,
                "error": "model output truncated",
                "error_code": "model_output_truncated",
                "output_truncated": True,
                "retryable": False,
                "terminal": True,
                "model": "fast-model",
            }
        return {
            "success": True,
            "model": "fast-model",
            "text": "SUMMARY: No actionable defects found.",
        }

    service = SimpleNamespace(
        config={},
        deterministic=None,
        incident_store=None,
        router=SimpleNamespace(classify=lambda *_args: {"model": "fast-model", "complexity": "fast"}),
        _resident_optimize=lambda route, *_args: route,
        model_policy=SimpleNamespace(
            tier_for=lambda _model: "fast",
            profile=lambda *_args, **_kwargs: SimpleNamespace(prompt_budget_tokens=32000),
        ),
        vram_balancer=None,
        delegate=delegate,
    )
    changes = "".join(f"-old_{i}_{'x' * 48}\n+new_{i}_{'y' * 48}\n" for i in range(24))
    diff = f"diff --git a/file.py b/file.py\n--- a/file.py\n+++ b/file.py\n@@ -1,24 +1,24 @@\n{changes}"

    result = LocalAIServices.review_diff(service, {"diff": diff, "max_tokens": 4096})

    review_contexts = [item["context"] for item in payloads if item.get("operation") == "review_diff"]
    assert result["success"] is True
    assert len(review_contexts) >= 3
    assert all(len(context) < len(review_contexts[0]) for context in review_contexts[1:])
    retried_lines = [
        line for context in review_contexts[1:] for line in context.splitlines()
        if line.startswith(("+new_", "-old_"))
    ]
    assert sorted(retried_lines) == sorted(
        line for line in diff.splitlines() if line.startswith(("+new_", "-old_"))
    )


def test_chunked_review_keeps_safe_output_floor_when_synthesis_budget_is_empty(monkeypatch):
    monkeypatch.setattr(services_module, "_REVIEW_SYNTHESIS_CONTEXT_TOKENS", 0)
    monkeypatch.setattr(services_module, "_REVIEW_DIFF_CONTEXT_FRACTION", 0.05)
    payloads = []

    def delegate(payload, **_kwargs):
        payloads.append(payload)
        return {
            "success": True,
            "model": "fast-model",
            "text": 'SUMMARY: No actionable defects found.\n```json\n{"verdict":"pass","findings":[]}\n```',
        }

    service = SimpleNamespace(
        config={},
        deterministic=None,
        incident_store=None,
        router=SimpleNamespace(classify=lambda *_args: {"model": "fast-model", "complexity": "fast"}),
        _resident_optimize=lambda route, *_args: route,
        model_policy=SimpleNamespace(
            tier_for=lambda _model: "fast",
            profile=lambda *_args, **_kwargs: SimpleNamespace(prompt_budget_tokens=32000),
        ),
        vram_balancer=None,
        delegate=delegate,
    )
    sections = []
    for filename in ("first.py", "second.py"):
        removed = "".join(f"-old_{index}_{'x' * 110}\n" for index in range(80))
        added = "".join(f"+new_{index}_{'y' * 110}\n" for index in range(80))
        sections.append(
            f"diff --git a/{filename} b/{filename}\n"
            f"--- a/{filename}\n+++ b/{filename}\n"
            f"@@ -1,80 +1,80 @@\n{removed}{added}"
        )
    diff = "".join(sections)

    result = LocalAIServices.review_diff(service, {"diff": diff, "max_tokens": 4096})

    review_budgets = [item["max_tokens"] for item in payloads if item.get("operation") == "review_diff"]
    assert result["success"] is True
    assert 2 <= len(review_budgets) <= 8
    assert min(review_budgets) >= 256
    assert max(review_budgets) <= 4096
