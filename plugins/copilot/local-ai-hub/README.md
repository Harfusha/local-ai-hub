# Local AI Hub for GitHub Copilot

This Agent Plugins 1.0 bundle provides the three shared Hub skills and a stdio MCP server entry. Install it through Copilot CLI's plugin marketplace or point the CLI at this directory.

The MCP launcher resolves `LOCAL_AI_HUB_DIR`, the standard `~/.local-ai-hub` install, or a Hub source checkout. Install the Hub first. MCP-only setup and the plugin MCP entry must not both be enabled, or tools will be duplicated.

The Agent Plugins bundle adds a `sessionStart` hook with concise Hub/Laya guidance. It returns context only and does not inspect prompts or change permissions. Hub setup separately installs managed `preToolUse` and `postToolUse` hooks under `COPILOT_HOME` (default `~/.copilot`); these events do not overlap with the plugin's `sessionStart` hook. The pre-tool hook applies bounded policy and cannot grant execution.

Copilot CLI and IDE hosts control plugin trust and hook execution. This bundle does not change permission settings or enable automatic tool approval.
