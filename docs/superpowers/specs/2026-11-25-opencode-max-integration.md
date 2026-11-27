# Maximum Local AI Hub and OpenCode Integration

## Status

Active scope. The user requested maximum Local AI Hub integration with OpenCode and directed continuation of the goal. This document records that scope; it grants no permissions beyond the user's request.

## User intent

Make OpenCode a first-class Local AI Hub client. OpenCode should discover and use the Hub's current tools, local model routes, repository context, task lifecycle, receipts, and GPU scheduling through documented native surfaces. The managed path should be local-first and security-bounded. Existing OpenCode configuration and user choices must survive setup and rollback.

## Current evidence and limits

- The live OpenCode installation is 2.2.5. Its current `mcp list` says no MCP servers are configured. Ollama is online and contains `gemma4:12b-128k` and `gemma4:12b`; neither fact proves OpenCode routing or GPU inference.
- The Hub emits `generated/opencode-mcp.json`, but the generated file is not installed or merged into OpenCode's config. Its agents are loaded in isolated probes, not in the user's current session.
- An experimental managed launcher filters inherited environment variables and scopes Hub credentials. It is not a filesystem or network sandbox.
- Windows ProcessContainer and loopback proxy probes block unwanted network paths in narrow tests. Strict ProcessContainer policy prevents OpenCode 2.2.5 from reaching its own local client/server transport (`EACCES`). A separate raw-AppContainer `SandboxSession` can run OpenCode with a fake model and shell tool through authenticated IPC using a test-only `taskkill` workaround, but it is not wired to setup, does not grant safe workspace access, and does not prove production process cleanup. Do not broaden host loopback access to bypass this.
- Fake-model probes cover parts of the goal plugin, bridge, installer, and sandbox. A managed launcher exists but is not the live OpenCode path; setup does not activate the provider/plugin. There is no verified managed real-model coding workflow, visible live MCP trust, cross-process goal recovery, or proven GPU exclusivity.

## Product behavior

- OpenCode connects to the running Hub over its documented MCP transport, using an explicitly configured profile and owned config entries. Setup previews changes, preserves unrelated settings, reports conflicts, and supports exact rollback.
- Hub tools and instructions are derived from the live capability schema and active hardware profile. Disabled or unauthorized actions are never advertised as usable.
- Model and context routing use Hub roles, live model inventory, explicit user choices, configured context limits, and current capacity. Explicit model selection remains authoritative. No silent cloud fallback, hidden provider request, or duplicate local-model endpoint is allowed.
- OpenCode coding, agents, subagents, and Hub-triggered inference acquire the same atomic GPU admission/fence before inference. Unknown ownership or shutdown state keeps the fence and blocks competing GPU work.
- A native OpenCode plugin supplies only host-provided session identity and lifecycle events. MCP remains the capability path. Task start, checkpoint, resume, cancellation, completion, and receipt verification bind to a real Agent OS task and authenticated session. Ordinary repository queries do not get fabricated task identities.
- Tool permissions remain host-controlled. OpenCode's agent permissions, MCP action scopes, Hub authorization, and user approval are checked independently; Laya or model output cannot grant permission, run commands, or approve receipts.
- The managed launcher isolates configuration and credentials, uses a constrained filesystem scope, disables model catalog fetch and automatic updates, and restricts network egress to verified Hub/model routes. A security boundary is claimed only after the actual OpenCode client/server transport works inside it.
- Prompts, source, and transcripts are not retained by default. Receipts contain bounded command identity, result, repository revision, task/session binding, and evidence references with secret redaction.

## Integration surfaces

1. **Setup and diagnostics:** version-aware OpenCode config generation/merge, preview, ownership markers, trust guidance, status and rollback.
2. **MCP and instructions:** live schema-derived Hub server, one consistent tool trigger guide, provider handshake and visible tool-load reporting.
3. **Model and context routing:** Hub role mapping, discovered local model IDs, max context validation, Q4 KV/config reporting, explicit choice precedence, GPU-aware admission.
4. **Native lifecycle plugin:** authenticated session context, task binding, checkpoint/resume/cancel, bounded event logging, and receipt handoff.
5. **GPU scheduler:** atomic admission across OpenCode and other local inference users, lease fencing, process ownership, confirmed shutdown and recovery.
6. **Managed launcher and containment:** isolated profile, secret allowlist, workspace grants, restricted broker, local endpoint identity, no broad host-loopback or unrestricted egress.
7. **Verification and operations:** diagnostics distinguish generated/configured/installed/trusted/connected/visible/runtime-verified; honest blockers and recovery commands.

## Acceptance criteria

1. On the installed OpenCode version, setup configures the Hub MCP server and supported agent/plugin surfaces without replacing unrelated OpenCode settings; preview and rollback preserve exact ownership.
2. A real OpenCode UI/CLI session shows the connected Hub and invokes an appropriate repository tool through its user-visible interface.
3. OpenCode selects the configured Gemma 4 12B Q4_K_M Hub route when eligible, respects the configured 128k context only when runtime memory/capacity validates it, and uses Q4 KV cache where the active server supports it. Explicit model choices are preserved.
4. A real local-model OpenCode coding task uses repository evidence and native Hub tools, runs an authorized verification command, writes authentic task-bound receipts, and completes only after receipt validation.
5. Session interruption, resume, and cancellation recover without repeating uncertain mutations or dropping task/session identity. Cross-process operations are fenced.
6. Concurrent OpenCode and Hub local inference cannot oversubscribe the GPU; unknown process or shutdown state fails closed and retains its lease.
7. Adversarial sandbox checks demonstrate the exact workspace grants, blocked unrelated files, blocked arbitrary network/cloud endpoints and secrets, and working OpenCode internal transport. If this cannot be achieved, the managed launcher reports the specific blocker and does not claim isolation or loosen policy.
8. Install, runtime, model, task, GPU, and sandbox results are separately recorded with fresh evidence. Stubs, fake models, static checks, and MCP handshake alone do not satisfy end-to-end acceptance.
9. Focused tests cover config preservation, schema/action filtering, route precedence, lifecycle idempotency, cancellation/recovery, receipt binding, GPU admission/fencing, and sandbox policy. Tests are not treated as proof of live runtime behavior.

## Out of scope

- Replacing or silently rewriting the user's OpenCode configuration.
- Automatically trusting plugins, approving commands, or enabling cloud providers.
- Reducing security restrictions to make the current experimental sandbox pass.
- Treating configured, installed, connected, or fake-model status as proof of a real-model run.
- Pulling models or changing active GPU, OpenCode, or Windows security settings without separate authorization from the user.

## Proposed implementation stages

1. Reconcile this scope into the active Hub plan; inspect OpenCode-related dirty source and define file ownership before implementation.
2. Complete non-mutating setup/config preview, live MCP schema integration, diagnostics, and rollback.
3. Complete Hub-aware local model/context routing and GPU admission across all OpenCode inference surfaces.
4. Complete the plugin-backed Agent OS session lifecycle, cancellation/recovery, and authentic receipts.
5. Resolve containment using a working restricted IPC/broker design or record a fail-closed product blocker.
6. Run focused checks, install through the managed setup path, then complete real UI/model/task/GPU/sandbox acceptance with fresh receipts.