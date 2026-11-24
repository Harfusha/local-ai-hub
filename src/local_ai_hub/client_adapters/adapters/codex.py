"""Codex adapter — app_server stream parsing, reasoning token tracking, and approval requests."""
from __future__ import annotations

from typing import Any
from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter


class CodexAdapter(BaseClientAdapter):
    client_id = "codex"
    capabilities = ClientCapabilities(
        client_id="codex",
        display_name="OpenAI Codex",
        hook_support=HookSupport.FULL,
        hook_events=("SessionStart", "UserPromptSubmit", "SubagentStart", "PreToolUse", "PermissionRequest", "PostToolUse"),
        instruction_targets=(InstructionTarget.AGENTS_MD,),
        has_token_tracking=True,
        has_reasoning_tokens=True,
        has_shadow_events=True,
        has_goal_system=False,
        prompt_cache_shield=True,
        mcp_surface="stdio",
    )

    def parse_hook_event(self, raw: Any) -> Any:
        if not isinstance(raw, str) or not raw.strip():
            return None
        from local_ai_hub.repo_plan.host_adapters import parse_codex_app_server_notification
        try:
            return parse_codex_app_server_notification(
                raw,
                sequence=0,
                repo_root=".",
                expected_cli_version="codex",
            )
        except (ValueError, TypeError, KeyError):
            return None

    def extract_token_usage(self, payload: dict[str, Any]) -> dict[str, int] | None:
        """Extract cumulative token usage from app_server tokenUsage updated notification."""
        token_usage = payload.get("params", {}).get("tokenUsage", {}).get("total", {})
        if not token_usage:
            return None
        return {
            "input_tokens": int(token_usage.get("inputTokens", 0)),
            "output_tokens": int(token_usage.get("outputTokens", 0)),
            "cache_read_tokens": int(token_usage.get("cachedInputTokens", 0)),
            "thinking_tokens": int(token_usage.get("reasoningOutputTokens", 0)),
            "total_tokens": int(token_usage.get("totalTokens", 0)),
        }


register_adapter("codex", CodexAdapter)
