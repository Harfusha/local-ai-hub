from __future__ import annotations

import math
import re
from typing import Any


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        return int(val)
    except (ValueError, TypeError, OverflowError):
        return default


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
DEFAULT_SEMANTIC_TERMS = {
    "explore", "exploring", "understand", "explain", "summarize", "summarise",
    "compare", "brainstorm", "propose", "suggest", "alternative", "counterargument",
    "prozkoumej", "prozkoumat", "vysvětli", "vysvetli", "shrň", "srovnej",
    "druhý názor", "druhy nazor", "zamysli",
}


def review_diff_complexity(
    args: dict[str, Any] | None, det_diff: dict[str, Any] | None, diff: dict[str, Any] | None
) -> str:
    """Escalate substantial or high-risk diff reviews to the heavy model tier."""
    args_dict = args if isinstance(args, dict) else {}
    det_dict = det_diff if isinstance(det_diff, dict) else {}
    diff_dict = diff if isinstance(diff, dict) else {}

    complexity = str(args_dict.get("complexity", "auto"))
    if complexity != "auto":
        return complexity

    risk = det_dict.get("risk", {})
    risk = risk if isinstance(risk, dict) else {}
    risk_score = _safe_int(risk.get("score") or det_dict.get("risk_score"), 0)
    risk_level = str(risk.get("level") or det_dict.get("risk_level") or "").lower()
    changed_files = diff_dict.get("changed_files")
    changed_file_count = len(changed_files) if isinstance(changed_files, list) else 0
    estimated_tokens = _safe_int(diff_dict.get("estimated_tokens"), 0)
    if (
        risk_level in {"high", "critical"}
        or risk_score >= 60
        or changed_file_count >= 6
        or estimated_tokens >= 3000
    ):
        return "heavy"
    return "auto"


class ModelRouter:
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config if isinstance(config, dict) else {}
        self.config = cfg
        models_cfg = cfg.get("models")
        if isinstance(models_cfg, dict):
            self.models = dict(models_cfg)
        else:
            self.models = {
                "background_code": "qwen2.5-coder:1.5b",
                "fast_code": "qwen2.5-coder:3b",
                "heavy_code": "qwen2.5-coder:7b",
                "reasoning": "qwen2.5-coder:7b",
                "general": "qwen2.5-coder:3b",
            }
        self.routing = cfg.get("routing", {}) if isinstance(cfg.get("routing"), dict) else {}
        self.complex_terms = set(self.routing.get("complex_terms", DEFAULT_COMPLEX_TERMS))
        self.reason_terms = set(self.routing.get("reason_terms", DEFAULT_REASON_TERMS))
        self.code_terms = set(self.routing.get("code_terms", DEFAULT_CODE_TERMS))
        self.review_terms = set(self.routing.get("review_terms", DEFAULT_REVIEW_TERMS))
        self.semantic_terms = set(self.routing.get("semantic_terms", DEFAULT_SEMANTIC_TERMS))

    def is_complex_term(self, term: str) -> bool:
        return str(term or "").strip().lower() in self.complex_terms

    def is_semantic_term(self, term: str) -> bool:
        return str(term or "").strip().lower() in self.semantic_terms

    def model_for_role(self, role: str) -> str:
        clean_role = str(role or "").strip().lower()
        return str(self.models.get(clean_role) or self.models.get("fast_code") or "qwen2.5-coder:3b")

    def complexity_score(self, task: str, context: str = "") -> int:
        task_str = str(task or "").replace("\x00", "")
        ctx_str = str(context or "").replace("\x00", "")
        text = f"{task_str}\n{ctx_str}".lower()
        score = 0
        total_chars = len(task_str) + len(ctx_str)
        if total_chars > 6000:
            score += 1
        max_fast = _safe_int(self.routing.get("max_fast_context_chars"), 90000)
        if total_chars > max_fast:
            score += 2
        score += min(sum(1 for term in self.complex_terms if term in text), 3)
        if text.count("\n") > 160:
            score += 1
        if len(re.findall(r"```|\bclass\b|\bfunction\b|\bdef\b|\bpublic\b|\bprivate\b", text)) >= 8:
            score += 1
        return score

    def classify(self, task: str, context: str = "", task_type: str = "auto", complexity: str = "auto") -> dict[str, Any]:
        task_str = str(task or "").replace("\x00", "")
        ctx_str = str(context or "").replace("\x00", "")
        text = f"{task_str}\n{ctx_str}".lower()
        task_text = task_str.lower()
        score = self.complexity_score(task_str, ctx_str)
        t_type = str(task_type or "auto").strip().lower()
        c_type = str(complexity or "auto").strip().lower()
        semantic_request = (
            t_type in {"general", "reasoning", "review"}
            or any(term in task_text for term in self.semantic_terms | self.reason_terms | self.review_terms)
        )

        if t_type == "auto":
            if any(term in task_text for term in self.review_terms):
                t_type = "review"
            elif any(term in task_text for term in self.semantic_terms | self.reason_terms):
                t_type = "reasoning"
            elif any(term in text for term in self.code_terms):
                t_type = "code"
            else:
                t_type = "general"

        heavy_key = "review_heavy_min_score" if t_type == "review" else "heavy_min_score"
        heavy_threshold = _safe_int(self.routing.get(heavy_key, self.routing.get("heavy_min_score", 5)), 5)
        if c_type == "heavy":
            score = max(score, heavy_threshold)
        elif c_type == "fast":
            score = 0

        heavy = score >= heavy_threshold
        if t_type in {"code", "review"}:
            model = self.models.get("heavy_code") if heavy else self.models.get("fast_code")
        elif t_type == "reasoning":
            # Ordinary reasoning uses the complex tier; only heavy reasoning uses the reasoning tier.
            model = (self.models.get("reasoning") or self.models.get("heavy_code")) if heavy else self.models.get("heavy_code")
        else:
            model = self.models.get("general") or self.models.get("fast_code")

        return {
            "task_type": t_type,
            "complexity_score": score,
            "complexity": "heavy" if heavy else "fast",
            "model": model,
            "semantic_required": semantic_request,
        }

    def apply_model_override(self, route: dict[str, Any] | None, requested_model: str = "") -> dict[str, Any]:
        route_dict = dict(route) if isinstance(route, dict) else {}
        requested = str(requested_model or "").replace("\x00", "").strip()
        if not requested or requested == str(route_dict.get("model", "")):
            return route_dict
        configured = {
            str(self.models.get(role))
            for role in ("background_code", "fast_code", "heavy_code", "reasoning", "general")
            if self.models.get(role)
        }
        if requested not in configured:
            raise ValueError("model override must match a configured model tier")

        task_type = str(route_dict.get("task_type", ""))
        complexity = str(route_dict.get("complexity", "fast"))
        if task_type == "reasoning":
            required_model = (
                self.models.get("reasoning") or self.models.get("heavy_code")
                if complexity == "heavy"
                else self.models.get("heavy_code") or route_dict.get("model")
            )
        elif task_type in {"code", "review"} and complexity == "heavy":
            required_model = self.models.get("heavy_code") or route_dict.get("model")
        else:
            required_model = route_dict.get("model")

        role_ranks = {
            "background_code": -1,
            "fast_code": 0,
            "general": 0,
            "heavy_code": 1,
            "reasoning": 2,
        }

        def model_rank(model: Any) -> int:
            return max(
                (rank for role, rank in role_ranks.items() if str(self.models.get(role, "")) == str(model or "")),
                default=0,
            )

        if model_rank(requested) < model_rank(required_model):
            raise ValueError("model override would fall below the configured quality floor")

        result = dict(route_dict)
        result["original_model"] = route_dict.get("model")
        result["model"] = requested
        result["model_override"] = True
        return result
