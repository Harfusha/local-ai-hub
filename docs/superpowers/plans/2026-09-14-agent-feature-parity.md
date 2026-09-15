# Agent feature parity implementation plan

Spec: `docs/superpowers/specs/2026-09-14-agent-feature-parity.md`

1. Derive MCP and generated instruction wording from `FeatureSet`; include Agent OS task lifecycle and enabled action families without advertising disabled features.
2. Synchronize the checked-in orchestrator skill, tool reference, `AGENTS.md`, and install/update prompts while preserving pre-existing user edits.
3. Add focused generator/description tests for Agent OS on/off and work-orchestrator on/off.
4. Run focused and repository validation through the Local AI Hub command broker; review the resulting diff and feature-gate behavior.
