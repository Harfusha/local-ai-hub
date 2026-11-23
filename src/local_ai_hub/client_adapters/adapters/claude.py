"""Claude Code adapter — prompt cache stabilization and hierarchical CLAUDE.md integration."""
from __future__ import annotations

from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter


class ClaudeAdapter(BaseClientAdapter):
    client_id = "claude"
    capabilities = ClientCapabilities(
        client_id="claude",
        display_name="Anthropic Claude Code",
        hook_support=HookSupport.NONE,
        instruction_targets=(InstructionTarget.CLAUDE_MD, InstructionTarget.AGENTS_MD),
        has_token_tracking=False,
        has_reasoning_tokens=True,
        has_shadow_events=False,
        has_goal_system=False,
        prompt_cache_shield=True,
        mcp_surface="stdio",
    )

    def get_instructions(self, target: InstructionTarget) -> str:
        base = super().get_instructions(target)
        if target == InstructionTarget.CLAUDE_MD:
            header = (
                "# Local AI Hub Integration\n\n"
                "> This repository uses Local AI Hub for local model inference, code indexing, and Agent OS.\n"
                "> Prioritize `local-ai` MCP server tools over unconstrained broad file reads or shell greps.\n\n"
            )
            return header + base
        return base


register_adapter("claude", ClaudeAdapter)
