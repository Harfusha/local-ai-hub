# Deterministic Local AI Hub Installer

## Intent

Finish the existing `install.ps1` / `install.sh` and `tools/setup.py` flow so a person can install, update, repair, or reinstall Local AI Hub without asking an AI to execute each step. The installer should make routine choices interactively, remember them, detect hardware-dependent components, and apply deterministic setup to supported agents.

## Goals

- Keep one deterministic setup engine for first install, update, repair, and reinstall.
- Offer a terminal wizard when setup runs without explicit choices in an interactive terminal; keep scripted and agent-driven calls non-interactive.
- Save the last selected profile and component choices, with explicit flags taking precedence.
- Detect optional runtime needs from configuration, hardware, and installed packages. Install only compatible, requested components; report CPU fallback where an accelerator is unavailable.
- Pull configured models through the selected provider and report exact models skipped or unavailable.
- Configure supported MCP clients, skills, and generated agent instructions idempotently.
- Offer full reinstall with a clear preview and explicit typed confirmation before deleting the configured Hub state and installation data.
- Migrate state only through ordered, versioned, offline steps. Back up first, stop at the first failed step, and verify before advancing the version marker.
- Write a completion report with installed, skipped, failed, and manual actions. Link manual actions to a maintained guide and provide a copyable AI prompt where a vendor step cannot be automated safely.

## Constraints and safety

- Preserve the existing staged update transaction and its protections for `.venv`, `state`, `models`, and installed config.
- Preserve explicit provider choices. Never silently enable Ollama or replace a configured inference route.
- Do not guess agent config paths beyond the clients already supported by `configure_agents`.
- Never delete state during ordinary install or update. Full reinstall must show exact resolved paths and require typed confirmation.
- Symlink/junction paths, unknown state versions, corrupt state, and unsupported migrations fail closed with a recovery guide.
- Network downloads use pinned or configured versions and bounded timeouts. Missing network, credentials, host applications, or vendor-only UI steps become actionable manual items.

## Agent integration formats

- Configure each selected client through its documented user-level MCP, skill, and always-on instruction locations. Use the shared `~/.agents/skills` root where the client officially supports it; use a native skill root when it does not. Do not install the same skills into multiple roots that a client loads concurrently.
- Cursor: merge the generated Hub policy into `~/.cursor/rules/local-ai-hub.mdc` with an always-apply frontmatter rule. Cursor and Windsurf can use the shared `~/.agents/skills` root when enabled.
- Windsurf: merge a concise, always-on Hub rule into `~/.codeium/windsurf/memories/global_rules.md` and keep it under the documented 6,000-character limit. Install native skills under `~/.codeium/windsurf/skills` only when the shared skills root is disabled.
- VS Code/Copilot: merge generated policy into `~/.copilot/copilot-instructions.md` and install user skills under `~/.copilot/skills`.
- Back up changed user files and preserve unrelated content. A conflicting or unsupported interface becomes a reportable manual action; never guess a vendor path.

## Implementation boundary

Build in the existing Python installer. Keep prompt collection and preference storage in a focused helper module; leave dependency installation and agent configuration in `tools/setup.py`. Add a versioned offline migration runner and only register conversions supported by verified source formats. The wizard must not claim that a model or agent integration works until deterministic checks confirm it.

## Acceptance

1. A first interactive run presents safe defaults based on the current configuration and hardware.
2. A later run offers remembered choices; explicit CLI flags override them.
3. A non-interactive run never waits for input.
4. Updates preserve config, state, model cache, unrelated agent settings, and the existing transactional rollback behavior.
5. Full reinstall previews paths and requires explicit typed confirmation before removing data.
6. Supported migrations run oldest-to-newest, each once, under a verified backup; failures preserve the previous version marker.
7. Unsupported host steps and failed optional installs appear in a report with direct guide links and a copyable prompt.
8. Documentation describes install, update, repair, full reinstall, migrations, and recovery.

## Assumptions

- Existing config remains the source of truth for provider selection and model tags.
- The default install path and configured `server.state_dir` are authoritative; the wizard does not relocate them silently.
- “All models” means all models required by the selected profile and configured provider, not every model offered by each provider.
- Installing or updating an external agent application itself is outside scope when that application has no supported unattended interface.
