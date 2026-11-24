# Local AI Hub for Antigravity

Plugin bundles the Hub skills, repository rule, local MCP launch configuration,
and bounded lifecycle hooks. Install Hub separately. The launcher uses
`LOCAL_AI_HUB_DIR` when set, otherwise `~/.local-ai-hub`, then supports running
from a source checkout.

The plugin and setup-managed global configuration provide the same Hub MCP
server and hooks. Choose one installation route per Antigravity profile to avoid
duplicate tools and hooks. Plugin hooks remain subject to Antigravity review and
the host's own permission policy; Hub hooks do not enable terminal auto-execution.

Validate and install with the current Antigravity CLI:

```sh
agy plugin validate --strict ./plugins/antigravity/local-ai-hub
agy plugin install ./plugins/antigravity/local-ai-hub
agy plugin list
```
