"""Antigravity adapter — hook integration, stream parsing, and token economy enforcement."""
from __future__ import annotations

from typing import Any
from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter


class AntigravityAdapter(BaseClientAdapter):
    client_id = "antigravity"
    capabilities = ClientCapabilities(
        client_id="antigravity",
        display_name="Google Antigravity",
        hook_support=HookSupport.INVOCATION_TOOL,
        hook_events=("SessionStart", "PreToolUse", "PostToolUse"),
        instruction_targets=(InstructionTarget.GEMINI_MD, InstructionTarget.AGENTS_MD),
        has_token_tracking=True,
        has_reasoning_tokens=True,
        has_shadow_events=True,
        has_goal_system=False,
        mcp_surface="stdio",
    )

    def parse_hook_event(self, raw: Any) -> Any:
        from local_ai_hub.repo_plan.host_adapters import (
            parse_antigravity_post_tool_use_event,
            parse_antigravity_stream_event,
        )

        if isinstance(raw, dict):
            event_type = raw.get("type", "")
            if event_type in {"post_tool_use", "postToolUse", "PostToolUse"}:
                try:
                    return parse_antigravity_post_tool_use_event(raw)
                except (ValueError, TypeError, KeyError):
                    pass
            if event_type in {"init", "step", "result"}:
                try:
                    seq = int(raw.get("sequence", 0))
                    return parse_antigravity_stream_event(raw, sequence=seq)
                except (ValueError, TypeError, KeyError):
                    pass
        return None

    def mutate_tool_description(self, tool_name: str, description: str) -> str:
        if tool_name == "local_ai_task":
            return description + " (Antigravity note: call directly from planner turn; do not poll in loops)."
        return description


register_adapter("antigravity", AntigravityAdapter)
register_adapter("gemini_antigravity", AntigravityAdapter)
