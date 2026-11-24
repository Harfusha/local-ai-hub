"""Devin Local adapter for the shared Local AI Hub MCP service."""
from __future__ import annotations

from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter


class DevinAdapter(BaseClientAdapter):
    client_id = "devin"
    capabilities = ClientCapabilities(
        client_id="devin",
        display_name="Devin Local",
        hook_support=HookSupport.PRE_POST_TOOL,
        hook_events=("SessionStart", "PreToolUse", "PostToolUse"),
        instruction_targets=(InstructionTarget.AGENTS_MD,),
        has_token_tracking=False,
        has_reasoning_tokens=False,
        has_shadow_events=False,
        has_goal_system=False,
        mcp_surface="stdio",
    )


register_adapter("devin", DevinAdapter)
