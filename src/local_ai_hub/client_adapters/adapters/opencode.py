"""OpenCode adapter — JS plugin configuration, tool filtering, and Goal state machine integration."""
from __future__ import annotations

import os
from typing import Any
from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter

_OPENCODE_TOOLS = frozenset({
    "local_ai_status",
    "local_ai_repo",
    "local_ai_task",
    "local_ai_coord",
    "local_ai_artifact",
    "local_ai_rag",
    "local_ai_work",
})


class OpenCodeAdapter(BaseClientAdapter):
    client_id = "opencode"
    capabilities = ClientCapabilities(
        client_id="opencode",
        display_name="OpenCode",
        hook_support=HookSupport.JS_PLUGIN,
        hook_events=("context", "execute.after", "permission.evaluate"),
        instruction_targets=(InstructionTarget.SYSTEM_PROMPT,),
        has_token_tracking=False,
        has_reasoning_tokens=False,
        has_shadow_events=True,
        has_goal_system=True,
        prompt_cache_shield=True,
        tool_filter=_OPENCODE_TOOLS,
        mcp_surface="stdio",
        compact_mcp_schemas=True,
    )

    def get_js_plugin_server_config(
        self, hub_install_dir: str, python_exe: str, hub_port: int | None = None
    ) -> dict[str, Any]:
        """Generate storage configuration dictionary for tools/opencode_mcp/index.js."""
        env: dict[str, str] = {
            "OPENCODE_SESSION": "1",
            "LOCAL_AI_HUB_DIR": str(hub_install_dir),
            "LOCAL_AI_AGENT": "opencode",
            "LOCAL_AI_AGENT_PROFILE": "opencode",
        }
        if hub_port:
            env["LOCAL_AI_HUB_PORT"] = str(hub_port)
        if py_path := os.environ.get("PYTHONPATH"):
            env["PYTHONPATH"] = py_path
        return {
            "command": [str(python_exe), "-m", "local_ai_hub.mcp_server"],
            "cwd": str(hub_install_dir),
            "environment": env,
        }

    def get_goal_system_prompt(self) -> str:
        """Compose the runtime system prompt for OpenCode Goal sessions."""
        from local_ai_hub.repo_plan.host_adapters import get_managed_planner_instructions
        return (
            "## Local AI Hub Integration\n\n"
            "You have access to the `local-ai` MCP server with core tools: "
            "`local_ai_status`, `local_ai_repo`, `local_ai_task`, `local_ai_coord`, "
            "`local_ai_artifact`, and `local_ai_rag`. `local_ai_work` appears only when the live MCP schema "
            "advertises it and the Hub's feature gates allow it. Use it only for explicitly requested, "
            "bounded delegation; never delegate the current task recursively.\n\n"
            + get_managed_planner_instructions()
        )


register_adapter("opencode", OpenCodeAdapter)
