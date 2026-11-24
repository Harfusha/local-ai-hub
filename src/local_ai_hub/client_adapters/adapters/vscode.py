"""VS Code and GitHub Copilot adapter — .vscode/mcp.json generator and copilot-instructions."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from ..base import BaseClientAdapter, ClientCapabilities, HookSupport, InstructionTarget
from ..registry import register_adapter


class VSCodeCopilotAdapter(BaseClientAdapter):
    client_id = "vscode"
    capabilities = ClientCapabilities(
        client_id="vscode",
        display_name="VS Code / GitHub Copilot",
        hook_support=HookSupport.PRE_POST_TOOL,
        hook_events=("sessionStart", "preToolUse", "postToolUse"),
        instruction_targets=(InstructionTarget.COPILOT_MD, InstructionTarget.AGENTS_MD),
        has_token_tracking=False,
        has_reasoning_tokens=False,
        has_shadow_events=False,
        has_goal_system=False,
        mcp_surface="stdio",
    )

    def generate_vscode_mcp_config(self, python_exe: str | Path, install_dir: str | Path) -> dict[str, Any]:
        """Generate official VS Code 1.96+ .vscode/mcp.json configuration dictionary."""
        return {
            "servers": {
                "local-ai": {
                    "type": "stdio",
                    "command": str(python_exe),
                    "args": ["-m", "local_ai_hub.mcp_server"],
                    "env": {
                        "LOCAL_AI_AGENT": "vscode",
                    },
                    "cwd": str(install_dir),
                }
            }
        }

    def get_mcp_config(self, hub_install_dir: str | Path, python_exe: str | Path | None = None) -> dict[str, Any]:
        import sys
        return self.generate_vscode_mcp_config(python_exe or sys.executable, hub_install_dir)


register_adapter("vscode", VSCodeCopilotAdapter)
register_adapter("copilot", VSCodeCopilotAdapter)
