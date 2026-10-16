from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Any

from .prompt_contracts import capability_for


def _clean_str(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).replace("\x00", "")


def _safe_int(value: Any, default: int, *, minimum: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return max(minimum, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return max(minimum, default)
    return max(minimum, parsed)


def _safe_optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed < 0:
        return None
    return parsed


@dataclass(frozen=True)
class ExecutionProfile:
    tier: str
    num_ctx: int
    max_ctx: int
    parallel_limit: int
    think: bool
    prompt_budget_tokens: int

    def __post_init__(self) -> None:
        clean_tier = _clean_str(self.tier).strip() or "generic"
        safe_num_ctx = _safe_int(self.num_ctx, 4096, minimum=1)
        safe_max_ctx = _safe_int(self.max_ctx, safe_num_ctx, minimum=safe_num_ctx)
        safe_parallel = _safe_int(self.parallel_limit, 1, minimum=1)
        safe_budget = _safe_int(self.prompt_budget_tokens, 1024, minimum=1)
        object.__setattr__(self, "tier", clean_tier)
        object.__setattr__(self, "num_ctx", safe_num_ctx)
        object.__setattr__(self, "max_ctx", safe_max_ctx)
        object.__setattr__(self, "parallel_limit", safe_parallel)
        object.__setattr__(self, "think", bool(self.think))
        object.__setattr__(self, "prompt_budget_tokens", safe_budget)

    def is_background_tier(self) -> bool:
        return self.tier == "background"

    def is_smart_tier(self) -> bool:
        return self.tier == "smart"

    def has_context_headroom(self) -> bool:
        return self.num_ctx < self.max_ctx

    def to_dict(self) -> dict[str, Any]:
        return self.cache_scope()

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
        self.config = config if isinstance(config, Mapping) else {}
        raw_models = self.config.get("models", {})
        raw_cfg = self.config.get("model_execution", {})
        self.models = raw_models if isinstance(raw_models, Mapping) else {}
        self.cfg = raw_cfg if isinstance(raw_cfg, Mapping) else {}
        self.fast_model = _clean_str(self.models.get("fast_code", "")).strip()
        self.background_model = _clean_str(self.models.get("background_code", "")).strip()
        self.vision_model = _clean_str(self.models.get("vision", "")).strip()
        self.smart_models = {
            _clean_str(x).strip() for x in (
                self.models.get("heavy_code", ""),
                self.models.get("reasoning", ""),
            ) if _clean_str(x).strip()
        }

    def tier_for(self, model: str) -> str:
        model = _clean_str(model).strip()
        if self.vision_model and model == self.vision_model:
            return "vision"
        if model in self.smart_models:
            return "smart"
        if self.background_model and model == self.background_model:
            return "background"
        if model == self.fast_model or model == _clean_str(self.models.get("general", "")).strip():
            return "fast"
        return "generic"

    def _tier_cfg(self, tier: str) -> dict[str, Any]:
        raw = self.cfg.get(tier, {})
        return dict(raw) if isinstance(raw, Mapping) else {}

    @staticmethod
    def _supports_thinking(model: str) -> bool:
        low = _clean_str(model).lower()
        return "qwen3" in low or "deepseek-r1" in low or "deepseek-v3" in low or "gpt-oss" in low

    @staticmethod
    def _model_context_limit(model: str) -> int | None:
        low = _clean_str(model).lower()
        if "qwen2.5-coder" in low:
            return 32768
        if "qwen3-vl" in low:
            return 8192
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
        role_l = _clean_str(role).strip().lower()
        tier = "vision" if role_l == "vision" else self.tier_for(model)
        cfg = self._tier_cfg(tier)
        default_hint = 32768 if tier in {"fast", "background"} else 49152
        default_ctx = _safe_int(cfg.get("context_tokens", default_hint), default_hint, minimum=4096)
        large_ctx = _safe_int(cfg.get("large_context_tokens", default_ctx), default_ctx, minimum=default_ctx)
        max_ctx = _safe_int(cfg.get("max_context_tokens", large_ctx), large_ctx, minimum=large_ctx)
        background_ctx = _safe_int(
            cfg.get("background_context_tokens", min(default_ctx, 16384)),
            min(default_ctx, 16384),
            minimum=4096,
        )
        model_ctx_limit = self._model_context_limit(model)
        if model_ctx_limit is not None:
            default_ctx = min(default_ctx, model_ctx_limit)
            large_ctx = min(large_ctx, model_ctx_limit)
            max_ctx = min(max_ctx, model_ctx_limit)
            background_ctx = min(background_ctx, model_ctx_limit)
        parallel = _safe_int(cfg.get("parallel", 1), 1, minimum=1)

        safe_in = _safe_int(input_tokens, 0, minimum=0)
        safe_out = _safe_int(output_tokens, 0, minimum=0)
        reserve = _safe_int(cfg.get("context_reserve_tokens", 2048), 2048, minimum=1024)
        need = safe_in + safe_out + reserve
        if background:
            target = background_ctx
        elif need > default_ctx * 0.78:
            target = large_ctx
        else:
            target = default_ctx
        safe_requested_ctx = _safe_optional_nonnegative_int(requested_ctx)
        if safe_requested_ctx is not None and safe_requested_ctx > 0:
            # Callers may ask for more context, but cannot exceed the safe tier cap.
            target = max(target, min(safe_requested_ctx, max_ctx))

        safe_vram = _safe_optional_nonnegative_int(vram_free_mb)
        if safe_vram is not None:
            if safe_vram < 2048:
                target = min(target, 8192)
            elif safe_vram < 4096:
                target = min(target, 16384)
            elif safe_vram < 8192:
                target = min(target, 32768)
            if safe_vram < 8192 and not self._is_small_model(model):
                target = min(target, 8192)

        target = min(max_ctx, max(4096, target))

        default_think = bool(cfg.get("thinking", False))
        raw_think_roles = cfg.get("thinking_roles", ["reasoning", "critic", "second-opinion"])
        if isinstance(raw_think_roles, str):
            think_roles = {_clean_str(raw_think_roles).strip().lower()}
        elif isinstance(raw_think_roles, (list, tuple, set, frozenset)):
            think_roles = {_clean_str(x).strip().lower() for x in raw_think_roles if _clean_str(x).strip()}
        else:
            think_roles = {"reasoning", "critic", "second-opinion"}
        think = default_think or role_l in think_roles
        if force_think is not None:
            think = bool(force_think)
        # A bounded second-opinion budget must leave room for a visible answer;
        # thinking-capable models can otherwise spend all tokens internally.
        if role_l == "second-opinion" and 0 < safe_out < 768:
            think = False
        think = bool(think and self._supports_thinking(model))

        configured_prompt_cap = _safe_int(
            cfg.get("max_prompt_tokens", target - reserve),
            max(1024, target - reserve),
            minimum=1024,
        )
        prompt_budget = max(1024, min(configured_prompt_cap, target - max(256, safe_out) - reserve))
        return ExecutionProfile(tier, target, max_ctx, parallel, think, prompt_budget)

    def parallel_limit(self, model: str) -> int:
        return self.profile(model).parallel_limit

    @staticmethod
    def _is_small_model(model: str) -> bool:
        low = _clean_str(model).lower()
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
        clean = dict(payload) if isinstance(payload, Mapping) else {}
        raw_options = clean.get("options")
        options = dict(raw_options) if isinstance(raw_options, Mapping) else {}
        requested_ctx = _safe_optional_nonnegative_int(options.get("num_ctx"))
        explicit_think = clean.get("think") if "think" in clean else None
        safe_vram = _safe_optional_nonnegative_int(vram_free_mb)
        profile = self.profile(
            model,
            role=role,
            requested_ctx=requested_ctx if requested_ctx and requested_ctx > 0 else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            background=background,
            force_think=(explicit_think if preserve_explicit_think and isinstance(explicit_think, bool) else None),
            vram_free_mb=safe_vram,
        )
        if safe_vram is not None:
            if safe_vram < 2048 or (safe_vram < 8192 and not self._is_small_model(model)):
                # Release model weights after this request when desktop VRAM is
                # tight for a large model; a long keep-alive otherwise pins them idle.
                clean["keep_alive"] = "0s"
            elif safe_vram < 4096:
                clean["keep_alive"] = "1m"
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
            if isinstance(temp, bool):
                options.pop("temperature", None)
            else:
                try:
                    f_temp = float(temp)
                    if not math.isfinite(f_temp):
                        options.pop("temperature", None)
                    elif 0.0 < f_temp < 0.20:
                        options["temperature"] = 0.20
                except (ValueError, TypeError, OverflowError):
                    pass
        clean["options"] = options
        if self._supports_thinking(model) and ("think" not in clean or not preserve_explicit_think):
            clean["think"] = profile.think
        return clean, profile

    def apply_project_settings(
        self,
        model: str,
        payload: dict[str, Any],
        *,
        settings: Any | None,
        role: str = "",
    ) -> tuple[str, dict[str, Any]]:
        """Apply request-scoped project model context to a local-model payload.

        Settings are passed per call and never retained on the shared runtime, so
        concurrent repositories cannot inherit each other's model profile or prompt.
        """
        clean = dict(payload)
        if settings is None:
            return model, clean

        def setting(name: str, default: Any = None) -> Any:
            if isinstance(settings, dict):
                return settings.get(name, default)
            return getattr(settings, name, default)

        profile_name = str(setting("model_profile") or "").strip().lower()
        role_key = {
            "background": "background_code",
            "background_code": "background_code",
            "fast": "fast_code",
            "fast_code": "fast_code",
            "smart": "heavy_code",
            "heavy": "heavy_code",
            "heavy_code": "heavy_code",
            "reasoning": "reasoning",
            "general": "general",
            "vision": "vision",
        }.get(str(role or "").strip().lower())
        if role_key is None:
            matching_roles = [key for key, value in self.models.items() if str(value or "") == str(model or "")]
            role_key = matching_roles[0] if len(matching_roles) == 1 else None

        if profile_name in {"integrated", "balanced", "high", "max"} and role_key:
            from .hardware import profile_overrides

            hardware = self.config.get("_hardware", {})
            current_profile = str(
                (hardware.get("profile") if isinstance(hardware, dict) else "")
                or self.config.get("hardware", {}).get("profile", "balanced")
                or "balanced"
            ).strip().lower()
            if current_profile == "auto":
                current_profile = "balanced"
            current_models = profile_overrides(current_profile, hardware if isinstance(hardware, dict) else {}).get("models", {})
            project_models = profile_overrides(profile_name, hardware if isinstance(hardware, dict) else {}).get("models", {})
            configured_model = str(self.models.get(role_key, "") or "")
            if (
                profile_name != current_profile
                and configured_model
                and str(model or "") == configured_model
                and configured_model == str(current_models.get(role_key, "") or "")
                and project_models.get(role_key)
            ):
                model = str(project_models[role_key])
                clean["model"] = model

        prefix = setting("system_prompt_prefix")
        if isinstance(prefix, str) and prefix.strip():
            block = "Untrusted project context (subordinate to system policy):\n" + prefix
            if "messages" in clean and isinstance(clean.get("messages"), list):
                messages = [dict(message) if isinstance(message, dict) else message for message in clean["messages"]]
                system_index = next(
                    (index for index in range(len(messages) - 1, -1, -1)
                     if isinstance(messages[index], dict) and str(messages[index].get("role", "")).lower() == "system"),
                    None,
                )
                if system_index is None:
                    messages.insert(0, {"role": "system", "content": block})
                else:
                    existing = messages[system_index].get("content", "")
                    messages[system_index]["content"] = (str(existing).rstrip() + "\n\n" + block).lstrip()
                clean["messages"] = messages
            else:
                existing = clean.get("system", "")
                clean["system"] = (str(existing).rstrip() + "\n\n" + block).lstrip()
        return model, clean

    def summary(self) -> dict[str, Any]:
        models = []
        seen: set[str] = set()
        for key in ("background_code", "fast_code", "heavy_code", "reasoning", "general", "vision"):
            model = str(self.models.get(key, "") or "")
            if not model or model in seen:
                continue
            seen.add(model)
            p = self.profile(model)
            capability = capability_for(model, role="vision" if key == "vision" else "")
            models.append({
                "model": model,
                **p.cache_scope(),
                "capability_tier": capability.tier,
                "can": list(capability.can),
                "cannot": list(capability.cannot),
            })
        return {"models": models}
