from __future__ import annotations

import re
from typing import Any


DEFAULT_COMPLEX_TERMS = {
    "architecture", "architect", "concurrency", "race condition", "deadlock", "security",
    "migration", "refactor", "performance", "distributed", "transaction", "rollback",
    "multi-thread", "multithread", "async", "root cause", "cross-file", "multi-file",
    "breaking change", "backward compatibility", "database schema", "protocol",
}
DEFAULT_REASON_TERMS = {
    "why", "reason", "analyze", "analyse", "tradeoff", "trade-off", "root cause",
    "explain", "design", "architecture", "debug", "diagnose", "hypothesis",
}
DEFAULT_CODE_TERMS = {
    "code", "function", "class", "method", "diff", "patch", "test", "bug", "compile",
    "php", "python", "javascript", "typescript", "java", "c#", "rust", "golang", "sql",
    "api", "repository", "repo", "refactor", "implementation",
}
DEFAULT_REVIEW_TERMS = {"review", "audit", "inspect", "critique", "second opinion", "check this"}


class ModelRouter:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.models = config["models"]
        self.routing = config.get("routing", {})
        self.complex_terms = set(self.routing.get("complex_terms", DEFAULT_COMPLEX_TERMS))
        self.reason_terms = set(self.routing.get("reason_terms", DEFAULT_REASON_TERMS))
        self.code_terms = set(self.routing.get("code_terms", DEFAULT_CODE_TERMS))
        self.review_terms = set(self.routing.get("review_terms", DEFAULT_REVIEW_TERMS))

    def complexity_score(self, task: str, context: str = "") -> int:
        text = f"{task}\n{context}".lower()
        score = 0
        total_chars = len(task) + len(context)
        if total_chars > 6000:
            score += 1
        if total_chars > int(self.routing.get("max_fast_context_chars", 90000)):
            score += 2
        score += min(sum(1 for term in self.complex_terms if term in text), 3)
        if text.count("\n") > 160:
            score += 1
        if len(re.findall(r"```|\bclass\b|\bfunction\b|\bdef\b|\bpublic\b|\bprivate\b", text)) >= 8:
            score += 1
        return score

    def classify(self, task: str, context: str = "", task_type: str = "auto", complexity: str = "auto") -> dict[str, Any]:
        text = f"{task}\n{context}".lower()
        score = self.complexity_score(task, context)

        if task_type == "auto":
            if any(term in text for term in self.review_terms):
                task_type = "review"
            elif any(term in text for term in self.code_terms):
                task_type = "code"
            elif any(term in text for term in self.reason_terms):
                task_type = "reasoning"
            else:
                task_type = "general"

        heavy_threshold = int(self.routing.get(
            "review_heavy_min_score" if task_type == "review" else "heavy_min_score",
            self.routing.get("heavy_min_score", 5),
        ))
        if complexity == "heavy":
            score = max(score, heavy_threshold)
        elif complexity == "fast":
            score = 0

        heavy = score >= heavy_threshold
        if task_type in {"code", "review"}:
            model = self.models["heavy_code"] if heavy else self.models["fast_code"]
        elif task_type == "reasoning":
            # Basic reasoning stays on the resident Qwen 2.5 Coder tier. Promote
            # only genuinely complex reasoning to the configured smart model.
            model = self.models["heavy_code"] if heavy else self.models["fast_code"]
        else:
            model = self.models["general"]

        return {"task_type": task_type, "complexity_score": score, "complexity": "heavy" if heavy else "fast", "model": model}
