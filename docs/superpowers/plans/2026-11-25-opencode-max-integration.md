# Maximum Local AI Hub and OpenCode Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`. Implement each task in order; preserve the worktree and every user-owned change.

**Goal:** Make OpenCode a first-class Hub client with locally routed Gemma inference, authenticated task lifecycle and receipts, shared GPU admission, and a verified restricted launcher.

**Architecture:** Complete the existing experimental OpenCode V2 MCP/config, goal plugin, inference bridge, GPU reservation and Windows AppContainer pieces as one managed integration. The Hub remains the authority for model routing, task ownership, verification and GPU admission; OpenCode remains the authority for host permissions and user confirmation. Fail closed whenever identity, capacity, sandbox access or mutation outcome is uncertain.

**Tech Stack:** Python, OpenCode 2.2.5 V2 JSON/plugin APIs, Node.js plugin runtime, Ollama, Local AI Hub HTTP/MCP, Windows AppContainer/Named Pipes/Jobs, pytest.

**Spec:** [2026-11-25-opencode-max-integration.md](../specs/2026-11-25-opencode-max-integration.md)

## Global Constraints

- Preserve unrelated OpenCode configuration; use a Hub-owned isolated profile and exact rollback.
- Never infer installation, trust, visible MCP tools, task identity, GPU exclusivity, local-only behavior, or completion from a manifest or fake-model test.
- Keep explicit model choice authoritative; route the configured Gemma 4 12B Q4_K_M only when the runtime validates model identity, context and capacity.
- Permit 128k context and Q4 KV cache only when the live inference server confirms both effective settings and sufficient capacity.
- Do not silently call a cloud endpoint, allow arbitrary same-user inherited secrets, or broaden host loopback access.
- Keep GPU reservations on unknown request, process, child-tree, VRAM, or shutdown outcome; release only with exact owner evidence.
- Do not alter Windows ACLs or security policy outside the managed sandbox boundary without an explicit user request.

## Review Focus

- OpenCode 2.2.5's internal client/server IPC must keep working while network egress is constrained.
- Workspace junctions and concurrent reparse-point changes must not expose files outside the authorized checkout.
- Child processes and `taskkill /T` cleanup must terminate only the owned process tree.
- Prompt, project source, Hub master token, and model/provider credentials must not leak to the OpenCode shell tool or arbitrary endpoint.
- Unknown MCP, goal, model, or GPU outcomes must not trigger duplicate task mutations, inference, or premature lease release.

## File Map

- `tools/setup.py`, `tools/opencode_install.py`: install, config ownership, preview, rollback and diagnostics.
- `tools/opencode_mcp/index.js`, `generated/opencode-mcp.json`, provider generation: live-schema MCP and OpenCode V2 profile/agent definitions.
- `tools/opencode_goal/{index.js,core.js,transport.js}`, `plugins/opencode/local-ai-hub`: native commands/hooks, task/session lifecycle and receipt binding.
- `tools/opencode_local.py`, `tools/opencode_pipe_client.cjs`, sandbox modules: managed launcher, isolated config, IPC, workspace and process lifetime.
- `src/local_ai_hub/client_adapters/adapters/opencode.py`, inference and GPU scheduler modules: Hub routing, credential profile, model admission and lease fencing.
- `tests/test_client_adapter_opencode.py`, `tests/test_opencode_*.py`, OpenCode plugin tests, installer tests and `tests/test_gpu_capacity_lease.py`: focused unit/integration coverage; add tests next to changed behavior.
- `docs/OPENCODE.md`: evidence-based install, runtime, security status and exact unresolved blockers.

## Tasks

### 1. Baseline and integration contract

- [ ] Re-read the OpenCode source, generated artifacts, relevant dirty diffs in the original master checkout, and current installed OpenCode/Ollama status. Do not copy or discard unrelated dirty edits.
- [ ] Map every V2 MCP/config/agent/plugin surface to its setup/status/rollback code and existing test. Record only evidence observed from current source and runtime.
- [ ] Confirm Hub route id, installed Ollama model id, configured context and cache settings from the active profile; leave model and security settings unchanged during discovery.
- [ ] Run existing focused OpenCode setup/config tests only after the baseline contract is set; record exact command and result.

### 2. Native setup and visible MCP

- [ ] Add failing focused coverage for install preview, user-config preservation, owned-key merge/removal, rollback and malformed/conflicting OpenCode V2 config.
- [ ] Complete the managed setup path so it installs the generated Hub MCP config, agents, commands and plugin into an isolated per-launch OpenCode profile; never auto-trust a plugin or rewrite unrelated config.
- [ ] Expose diagnostics for generated, configured, installed, trusted, connected and user-visible tool states separately.
- [ ] Run targeted setup tests and verify `opencode mcp list` plus visible tools from the actual OpenCode client after install.

### 3. Hub model, context and GPU-aware routing

- [ ] Add focused tests for explicit-model precedence, installed-model discovery, `gemma4:12b-128k` route selection, local-only rejection, unsupported alias refusal and deterministic fallback.
- [ ] Route OpenCode inference through one Hub-owned model/session endpoint; validate context length, KV cache type, current Ollama owner identity, resident model and VRAM capacity on the same admitted connection.
- [ ] Add integration tests proving every OpenCode model request acquires the shared GPU fence, serializes competing inference and retains admission on truncation, disconnect or unknown outcome.
- [ ] Use a real Gemma inference only after current hardware/profile telemetry confirms safe admission; record actual context, cache, tokens/s, VRAM and process identity.

### 4. Agent OS task lifecycle and receipts

- [ ] Add plugin tests for create/bind, checkpoint, pause, resume, cancel, task/session mismatch, repeated event and unknown mutation response across separate plugin processes.
- [ ] Complete OpenCode command/plugin integration using documented session APIs. Keep taskless repository exploration taskless; bind lifecycle actions to an authenticated Agent OS task/session.
- [ ] Restrict verification to configured command aliases and exact project/task/session binding; persist request IDs before dispatch and accept only Hub-verified authentic receipts.
- [ ] Run a real model-driven coding task with one deliberate failing verification and one passing verification; ensure the first stays incomplete and only the latter can complete.

### 5. Managed launcher and production sandbox

- [ ] Add adversarial tests for config/environment/credential inheritance, unrelated file access, junction creation/swap, path escape, arbitrary local/external TCP, pipe impersonation, child-tree termination and interruption cleanup.
- [ ] Wire `SandboxSession` into setup/launcher with per-session identity, authenticated bounded IPC, fixed-target proxy, scoped workspace grants and owned Windows Job lifecycle.
- [ ] Replace the test-only `taskkill` workaround and prove actual OpenCode internal IPC, authorized project read/write, blocked external paths and process cleanup under the production policy.
- [ ] Keep the managed launch path disabled or explicitly incomplete if any sandbox property cannot be proven; record the exact blocker without weakening policy.

### 6. Install and end-to-end acceptance

- [ ] Run the focused test sets for each changed surface; do not run the unconstrained full suite.
- [ ] Install/activate the managed profile without disturbing unrelated OpenCode config or running Hub/Ollama sessions.
- [ ] Verify live OpenCode UI/CLI MCP visibility, real Gemma 4 12B Q4_K_M inference at effective 128k/Q4 KV settings, task pause/resume/cancel, authentic receipts, competing GPU admission and adversarial sandbox behavior.
- [ ] Update `docs/OPENCODE.md`, the Hub plan task and task checkpoint with real commands, outcomes, evidence identities and remaining limitations.
- [ ] Mark plan and Agent OS task complete only after every acceptance criterion has fresh candidate-bound evidence; otherwise preserve the goal active and record concrete blockers.
