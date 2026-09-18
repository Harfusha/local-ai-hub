from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionProfile:
    tier: str
    num_ctx: int
    max_ctx: int
    parallel_limit: int
    think: bool
    prompt_budget_tokens: int

    def cache_scope(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "num_ctx": self.num_ctx,
            "max_ctx": self.max_ctx,
            "parallel_limit": self.parallel_limit,
            "think": self.think,
            "prompt_budget_tokens": self.prompt_budget_tokens,
        }


class ModelExecutionPolicy:
    """Per-tier execution policy for a single constrained GPU.

    Ollama's OLLAMA_NUM_PARALLEL is process-global. Local AI keeps foreground fast/smart on
    one runtime and runs the opportunistic background coder on a separate, managed
    Ollama endpoint. This lets the background tier use higher concurrency without
    inflating the foreground runner's KV allocation.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.models = config.get("models", {})
        self.cfg = config.get("model_execution", {})
        self.fast_model = str(self.models.get("fast_code", ""))
        self.background_model = str(self.models.get("background_code", ""))
        self.smart_models = {
            str(x) for x in (
                self.models.get("heavy_code", ""),
                self.models.get("reasoning", ""),
            ) if x
        }

    def tier_for(self, model: str) -> str:
        model = str(model or "")
        if model in self.smart_models:
            return "smart"
        if self.background_model and model == self.background_model:
            return "background"
        if model == self.fast_model or model == str(self.models.get("general", "")):
            return "fast"
        return "generic"

    def _tier_cfg(self, tier: str) -> dict[str, Any]:
        raw = self.cfg.get(tier, {})
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _supports_thinking(model: str) -> bool:
        low = model.lower()
        return "qwen3" in low or "deepseek-r1" in low or "deepseek-v3" in low or "gpt-oss" in low

    @staticmethod
    def _model_context_limit(model: str) -> int | None:
        if "qwen2.5-coder" in str(model or "").lower():
            return 32768
        return None

    def profile(
        self,
        model: str,
        *,
        role: str = "",
        requested_ctx: int | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        background: bool = False,
        force_think: bool | None = None,
        vram_free_mb: int | None = None,
    ) -> ExecutionProfile:
        tier = self.tier_for(model)
        cfg = self._tier_cfg(tier)
        default_hint = 32768 if tier in {"fast", "background"} else 49152
        default_ctx = max(4096, int(cfg.get("context_tokens", default_hint)))
        large_ctx = max(default_ctx, int(cfg.get("large_context_tokens", default_ctx)))
        max_ctx = max(large_ctx, int(cfg.get("max_context_tokens", large_ctx)))
        background_ctx = max(4096, int(cfg.get("background_context_tokens", min(default_ctx, 16384))))
        model_ctx_limit = self._model_context_limit(model)
        if model_ctx_limit is not None:
            default_ctx = min(default_ctx, model_ctx_limit)
            large_ctx = min(large_ctx, model_ctx_limit)
            max_ctx = min(max_ctx, model_ctx_limit)
            background_ctx = min(background_ctx, model_ctx_limit)
        parallel = max(1, int(cfg.get("parallel", 1)))

        need = max(0, int(input_tokens)) + max(0, int(output_tokens)) + max(1024, int(cfg.get("context_reserve_tokens", 2048)))
        if background:
            target = background_ctx
        elif need > default_ctx * 0.78:
            target = large_ctx
        else:
            target = default_ctx
        if requested_ctx is not None and int(requested_ctx) > 0:
            # Callers may ask for more context, but cannot exceed the safe tier cap.
            target = max(target, min(int(requested_ctx), max_ctx))

        if vram_free_mb is not None and vram_free_mb > 0:
            if vram_free_mb < 2048:
                target = min(target, 8192)
            elif vram_free_mb < 4096:
                target = min(target, 16384)
            elif vram_free_mb < 8192:
                target = min(target, 32768)

        target = min(max_ctx, max(4096, target))

        role_l = str(role or "").lower()
        default_think = bool(cfg.get("thinking", False))
        think_roles = {str(x).lower() for x in cfg.get("thinking_roles", ["reasoning", "critic", "second-opinion"])}
        think = default_think or role_l in think_roles
        if force_think is not None:
            think = bool(force_think)
        # A bounded second-opinion budget must leave room for a visible answer;
        # thinking-capable models can otherwise spend all tokens internally.
        if role_l == "second-opinion" and 0 < int(output_tokens) < 768:
            think = False
        think = bool(think and self._supports_thinking(model))

        reserve = max(1024, int(cfg.get("context_reserve_tokens", 2048)))
        configured_prompt_cap = max(1024, int(cfg.get("max_prompt_tokens", target - reserve)))
        prompt_budget = max(1024, min(configured_prompt_cap, target - max(256, int(output_tokens)) - reserve))
        return ExecutionProfile(tier, target, max_ctx, parallel, think, prompt_budget)

    def parallel_limit(self, model: str) -> int:
        return self.profile(model).parallel_limit

    @staticmethod
    def _is_small_model(model: str) -> bool:
        low = str(model or "").lower()
        return any(tag in low for tag in ("0.5b", "1.5b", "3b", ":1b", ":2b"))

    def apply_payload(
        self,
        model: str,
        payload: dict[str, Any],
        *,
        role: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        background: bool = False,
        preserve_explicit_think: bool = True,
        vram_free_mb: int | None = None,
    ) -> tuple[dict[str, Any], ExecutionProfile]:
        clean = dict(payload)
        options = dict(clean.get("options", {}) or {})
        requested_ctx = options.get("num_ctx")
        explicit_think = clean.get("think") if "think" in clean else None
        profile = self.profile(
            model,
            role=role,
            requested_ctx=int(requested_ctx) if requested_ctx not in (None, "") else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            background=background,
            force_think=(explicit_think if preserve_explicit_think and isinstance(explicit_think, bool) else None),
            vram_free_mb=vram_free_mb,
        )
        options["num_ctx"] = profile.num_ctx
        if self._is_small_model(model):
            if "repeat_penalty" not in options:
                options["repeat_penalty"] = 1.18
            if "repeat_last_n" not in options:
                options["repeat_last_n"] = 128
        else:
            if "repeat_penalty" not in options:
                options["repeat_penalty"] = 1.12
            if "repeat_last_n" not in options:
                options["repeat_last_n"] = 64
        # Near-greedy sampling can make Qwen coder repeat fragments and emit
        # low-quality filler. Keep explicit temperature=0 for deterministic probes,
        # but give all generated text a small amount of sampling headroom.
        temp = options.get("temperature")
        if temp is not None:
            try:
                f_temp = float(temp)
                if 0.0 < f_temp < 0.20:
                    options["temperature"] = 0.20
            except (ValueError, TypeError):
                pass
        clean["options"] = options
        if self._supports_thinking(model) and ("think" not in clean or not preserve_explicit_think):
            clean["think"] = profile.think
        return clean, profile

    def summary(self) -> dict[str, Any]:
        models = []
        seen: set[str] = set()
        for key in ("background_code", "fast_code", "heavy_code", "reasoning", "general"):
            model = str(self.models.get(key, "") or "")
            if not model or model in seen:
                continue
            seen.add(model)
            p = self.profile(model)
            models.append({"model": model, **p.cache_scope()})
        return {"models": models}
