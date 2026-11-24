# Local AI Hub for Claude Code

Plugin packages Hub skills, MCP tools, and native Claude Code lifecycle hooks.
Install Local AI Hub separately. The launcher uses `LOCAL_AI_HUB_DIR` when set,
otherwise `~/.local-ai-hub`, then supports running from a source checkout.

The plugin and setup-managed global MCP/hooks provide the same capabilities.
Choose one route per Claude profile to avoid duplicate MCP servers and hook
invocations. Hook denials use Claude's native output; an ordinary result makes no
permission decision, leaving Claude's permission system in control.

For local development, run `claude --plugin-dir ./plugins/claude/local-ai-hub`.
