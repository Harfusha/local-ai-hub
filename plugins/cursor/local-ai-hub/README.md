# Local AI Hub for Cursor

Cursor-native plugin with shared Hub skills, MCP tools, repository guidance, session warmup, and a `beforeShellExecution` policy hook. The hook denies bounded unsafe commands and returns `ask` for clean commands, preserving Cursor approval. It does not approve or execute commands.

Install the plugin through Cursor's plugin flow or copy this folder to `~/.cursor/plugins/local/local-ai-hub` and reload Cursor. Cursor controls local-plugin trust. Do not enable this MCP entry alongside the standalone Hub MCP setup or duplicate hooks through Hub setup.
