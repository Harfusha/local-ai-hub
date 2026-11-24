# Laya and Provider Integration

## User intent

Laya is an actively used part of Local AI Hub. All providers advertised as supported by the Hub must have a complete, truthful integration through the surfaces each provider actually supports: MCP, skills/instructions, plugins, hooks, setup, and runtime handshake. Laya runs only for active typed decisions; background evaluation is not run.

## Product behavior

- The Hub owns one local Laya decision service shared by all providers. Do not create one model daemon or duplicate Laya state per provider.
- Active Laya decisions participate in ordinary Hub routing for retrieval strategy, context shaping, model tier selection, task guidance, and other registered low-risk Hub decisions. A valid suggestion is applied by the Hub without requiring a separate human copy step.
- Every decision remains typed, bounded, attributable to the provider/session, and scoped to the authorized repository/task. The Hub retains deterministic validation and a deterministic fallback for unavailable, malformed, low-confidence, or out-of-scope Laya results.
- Laya never grants host permissions, bypasses user approval, executes tools, changes task/receipt state, approves completion, or performs destructive operations. Those remain with the deterministic Hub and host.
- Inference stays local. Capture only data needed to reproduce an eligible decision; redact secrets, bound payloads, and preserve provenance. Human labels remain distinct from model reviews. Integration does not authorize model training, benchmark jobs, model downloads, publication, or rollout by itself.

## Provider contract

- Treat the enabled provider list in Hub configuration as the inventory source; currently inspect Codex, Antigravity/Gemini, Claude, Cursor, Windsurf, VS Code/Copilot, OpenCode, and extra MCP paths.
- MCP is the shared live capability surface. Each provider's installed skill/instructions must teach the same current Hub route and respect the live tool schema.
- Use native plugins/hooks only where the provider supports them. A hook may provide authenticated, bounded lifecycle context; it must not pretend to know prompts, permissions, or session identity that the host did not provide and verify.
- Setup must preserve unrelated host configuration, expose preview/apply/rollback where it writes hooks, report partial installation, and never auto-trust a host hook.
- Provider status distinguishes configured, installed, enabled, trusted, connected, and runtime-verified. Presence of a manifest or MCP entry is not proof of a working provider.
- Unsupported or unavailable surfaces are reported per provider with their fallback path. Do not claim universal hook parity when an API does not provide it.

## Acceptance criteria

1. A source-backed matrix names every enabled provider, supported MCP/skill/plugin/hook surfaces, installation path, trust requirements, verification method, and limitations.
2. Laya handles applicable decisions through active typed advisories. Evaluation uses only actual outcomes from these active calls; no passive comparison path exists.
3. Laya suggestions affect eligible routing decisions; failure/abstention uses deterministic behavior and records an honest status.
4. Codex, Antigravity/Gemini, Claude, and every other enabled provider receive matching instructions and working MCP setup; provider-specific hooks/plugins load only in documented layouts.
5. Provider identity, permissions, repository/task scope, privacy bounds, and deterministic high-impact gates remain enforced.
6. Setup and diagnostics report per-provider installation and live-handshake state accurately; documentation does not claim unverified coverage.
7. Focused automated checks cover each changed adapter and Laya route. Host/runtime acceptance is reported separately for clients unavailable in the current environment.

## Implementation sequence

1. Inventory enabled providers and current source/test coverage; inspect dirty work without overwriting it.
2. Reconcile the existing Laya and provider-routing plans to this steering and split work by independently testable subsystem.
3. Wire active Laya decisions into the central Hub paths; verify deterministic fallback and high-impact boundaries.
4. Normalize each provider's MCP, skill/instruction, plugin, and hook packaging to current host formats; update setup and status reporting.
5. Validate each changed surface and record which installed clients completed a real handshake.
