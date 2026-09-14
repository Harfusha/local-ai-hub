from __future__ import annotations

import re
from typing import Any


DEFAULT_COMPLEX_TERMS = {
    "architecture", "architect", "concurrency", "race condition", "deadlock", "security",
    "migration", "refactor", "performance", "distributed", "transaction", "rollback",
    "multi-thread", "multithread", "async", "root cause", "cross-file", "multi-file",
    "breaking change", "public API contract", "database schema", "protocol",
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


def review_diff_complexity(
    args: dict[str, Any], det_diff: dict[str, Any], diff: dict[str, Any]
) -> str:
    """Escalate substantial or high-risk diff reviews to the heavy model tier."""
    complexity = str(args.get("complexity", "auto"))
    if complexity != "auto":
        return complexity

    risk = det_diff.get("risk", {})
    risk = risk if isinstance(risk, dict) else {}
    risk_score = int(risk.get("score") or det_diff.get("risk_score") or 0)
    risk_level = str(risk.get("level") or det_diff.get("risk_level") or "").lower()
    changed_file_count = len(diff.get("changed_files", []))
    estimated_tokens = int(diff.get("estimated_tokens", 0) or 0)
    if (
        risk_level in {"high", "critical"}
        or risk_score >= 60
        or changed_file_count >= 6
        or estimated_tokens >= 3000
    ):
        return "heavy"
    return "auto"


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
            # Reasoning always uses the configured reasoning tier, regardless of task size.
            model = self.models.get("reasoning") or self.models["heavy_code"]
        else:
            model = self.models["general"]

        return {"task_type": task_type, "complexity_score": score, "complexity": "heavy" if heavy else "fast", "model": model}

    def apply_model_override(self, route: dict[str, Any], requested_model: str = "") -> dict[str, Any]:
        requested = str(requested_model or "").strip()
        if not requested or requested == str(route.get("model", "")):
            return route
        configured = {
            str(self.models.get(role))
            for role in ("fast_code", "heavy_code", "reasoning", "general")
            if self.models.get(role)
        }
        if requested not in configured:
            raise ValueError("model override must match a configured model tier")
        result = dict(route)
        result["original_model"] = route.get("model")
        result["model"] = requested
        result["model_override"] = True
        return result
