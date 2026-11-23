"""Gemini CLI adapter — native extension verification and settings.json hooks."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter


class GeminiCliAdapter(BaseClientAdapter):
    client_id = "gemini_cli"
    capabilities = ClientCapabilities(
        client_id="gemini_cli",
        display_name="Gemini CLI (Google)",
        hook_support=HookSupport.FULL,
        instruction_targets=(InstructionTarget.GEMINI_MD, InstructionTarget.AGENTS_MD),
        has_token_tracking=False,
        has_reasoning_tokens=False,
        has_shadow_events=False,
        has_goal_system=False,
        mcp_surface="stdio",
    )

    def verify_superpowers(self, source_root: str | Path | None = None) -> dict[str, Any]:
        """Verify presence and compatibility of Superpowers extension."""
        from local_ai_hub.repo_plan.host_hooks import inspect_superpowers
        return inspect_superpowers("gemini_cli", source_root)


register_adapter("gemini_cli", GeminiCliAdapter)
