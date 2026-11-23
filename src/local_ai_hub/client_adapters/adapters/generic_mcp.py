"""Generic MCP adapter — resilient fallback for unknown or generic MCP clients."""
from __future__ import annotations

from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter


class GenericMcpAdapter(BaseClientAdapter):
    client_id = "generic_mcp"
    capabilities = ClientCapabilities(
        client_id="generic_mcp",
        display_name="Generic MCP Client",
        hook_support=HookSupport.NONE,
        instruction_targets=(InstructionTarget.AGENTS_MD,),
        has_token_tracking=False,
        has_reasoning_tokens=False,
        has_shadow_events=False,
        has_goal_system=False,
        mcp_surface="stdio",
    )


register_adapter("generic_mcp", GenericMcpAdapter)
