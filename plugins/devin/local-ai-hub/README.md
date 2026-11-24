# Local AI Hub for Devin Local

This Agent Plugin provides the shared Local AI Hub MCP server and the Hub's
provider skills. Install locally with `devin plugins install --local <path>`
after reviewing the plugin contents and approving its host permissions.
The manifest restricts it to Devin Local sessions; its stdio MCP launcher
requires a local Hub installation and is not a cloud session service.

The plugin includes MCP, skills, and a `SessionStart` context hook that reminds
Devin when to use the shared MCP and keeps host approvals authoritative. Devin
plugin hooks are best-effort, so this hook provides context only. `tools/setup.py`
configures the separate user-level `PreToolUse` policy hook.
Set `agents.devin_plugin_route = true` before setup to select this plugin route;
setup then skips new global MCP/skill installation and reports any old global
MCP route for reviewed cleanup. Install the plugin through Devin's documented
CLI after reviewing its contents and host trust requirements.
