"""Cursor and Windsurf adapters — clean markdown rules and lean MCP surface."""
from __future__ import annotations

from typing import Any

from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter


def _clean_markdown_rules(text: str) -> str:
    """Format instructions cleanly without HTML comment tags for IDE rule parsers."""
    cleaned = text.replace("<!-- BEGIN LOCAL AI HUB PLANNER -->", "## Local AI Hub Project Planner")
    cleaned = cleaned.replace("<!-- END LOCAL AI HUB PLANNER -->", "")
    cleaned = cleaned.replace("<!-- BEGIN LOCAL AI HUB TOOL POLICY -->", "## Local AI Hub Tool Policy")
    cleaned = cleaned.replace("<!-- END LOCAL AI HUB TOOL POLICY -->", "")
    return cleaned.strip() + "\n"


class CursorAdapter(BaseClientAdapter):
    client_id = "cursor"
    capabilities = ClientCapabilities(
        client_id="cursor",
        display_name="Cursor IDE",
        hook_support=HookSupport.SESSION_PRE_POST_TOOL,
        hook_events=("sessionStart", "beforeShellExecution", "afterFileEdit"),
        instruction_targets=(InstructionTarget.CURSORRULES, InstructionTarget.CURSOR_MDC),
        has_token_tracking=False,
        has_reasoning_tokens=False,
        has_shadow_events=False,
        has_goal_system=False,
        mcp_surface="stdio",
    )

    def get_instructions(self, target: InstructionTarget) -> str:
        return _clean_markdown_rules(super().get_instructions(target))

    def parse_hook_event(self, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return None
        from local_ai_hub.repo_plan.host_adapters import parse_cursor_session_start_event
        try:
            return parse_cursor_session_start_event(raw)
        except (ValueError, TypeError, KeyError):
            return None


class WindsurfAdapter(BaseClientAdapter):
    client_id = "windsurf"
    capabilities = ClientCapabilities(
        client_id="windsurf",
        display_name="Windsurf IDE (Codeium)",
        hook_support=HookSupport.PRE_POST_TOOL,
        hook_events=("pre_run_command", "pre_read_code", "pre_mcp_tool_use", "post_write_code"),
        instruction_targets=(InstructionTarget.WINDSURFRULES,),
        has_token_tracking=False,
        has_reasoning_tokens=False,
        has_shadow_events=False,
        has_goal_system=False,
        mcp_surface="stdio",
    )

    def get_instructions(self, target: InstructionTarget) -> str:
        return _clean_markdown_rules(super().get_instructions(target))


register_adapter("cursor", CursorAdapter)
register_adapter("windsurf", WindsurfAdapter)
