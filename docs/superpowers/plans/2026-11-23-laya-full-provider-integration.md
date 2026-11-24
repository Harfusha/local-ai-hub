# Laya and Provider Integration Implementation Plan

> **For agentic workers:** Work from the active Hub plan and this specification. Keep each subsystem independently reviewable.

**Goal:** Make Laya an active local decision service for eligible Hub flows and give every enabled provider a consistent, verified Hub integration.

**Architecture:** One Hub-owned Laya runtime serves all provider clients. Shared MCP and generated skills provide the common route; provider-specific setup and hooks adapt only to verified host capabilities. The Hub validates Laya output, applies eligible low-risk recommendations, and uses deterministic fallback. Host permissions and high-impact actions remain outside Laya authority.

**Scope:** Codex; Antigravity/Gemini; Claude; Cursor; Windsurf; VS Code/Copilot; OpenCode if still enabled/supported by current master; configured extra MCP paths. Resolve provider support against source and current official host documentation before claiming coverage.

## Task 1: Inventory and plan alignment

- [x] Inspect current provider configuration, generated/installed skills, MCP manifests, hooks, setup, and tests.
- [ ] Reuse active Laya and provider-routing Hub plans; record the new steering and link this specification and plan. **Deferred 2026-11-24 per user instruction:** do not use Local AI Hub in this pass. Plan JSON was not edited directly; this Markdown implementation plan remains the supported project-plan record.
- [x] Preserve the existing dirty tree; do not overwrite unrelated Laya runtime, model packaging, installer, or documentation changes.
- [x] Produce a provider matrix with install, trust, connection, and live verification state.

## Task 2: Activate Laya in central Hub decisions

- [x] Trace the existing Laya gateway, decision service, runtime, and all decision callers.
- [x] Route eligible retrieval/context/model-tier/task-guidance decisions through Laya in normal operation.
- [ ] Apply valid low-risk neural Laya decisions centrally; retain deterministic validation, abstention, bounded capture, and fallback. **Active path implemented:** when Laya is enabled, pinned checkpoint/config validates, eligible model routes exist, and verified task evidence is present, the normal pipeline calls the typed advisory evaluator and applies only an allowlisted suggestion. Fixture tests prove route/retrieval/context/next-step application and deterministic baseline floors; evaluators are mocked, so actual model inference, abstention quality, and device acceptance remain unverified.
- [x] Keep permission, tool execution, task/receipt mutation, completion approval, and destructive operations under deterministic Hub/host control.
- [x] Ensure unavailable model/runtime states are reported without blocking ordinary Hub use.

## Task 3: Complete provider surfaces

- [x] Make MCP and generated agent skills/instructions share one live capability source and current usage workflow. **Implemented 2026-11-24:** live `tools/list` is authoritative for available tools, action enums, and fields; skill action lists are snapshots; seven provider bundles mirror the canonical skill, while OpenCode receives it from setup's discovered global skills directory.
- [x] Normalize Codex plugin packaging and hook discovery to current Codex layouts; preserve explicit trust review.
- [ ] Verify Antigravity/Gemini and Claude setup/plugin/hook surfaces separately; cover Cursor, Windsurf Cascade, Devin Local, Copilot, OpenCode, and extra MCP paths according to their supported surfaces. **Partial:** Added native Antigravity, Claude, Copilot, Cursor, and Devin Agent Plugin bundles plus a Gemini CLI extension, with shared skills and portable MCP launchers; Antigravity and Devin CLI validation and provider plugin runtime handshakes remain unavailable. Global Antigravity setup injects static MCP/Laya guidance and enforces bounded tool policy. Cursor's shell hook denies bounded violations and retains native approval on clean calls; `afterFileEdit` runs the shared static check. Claude's `PostToolUse` checks `Edit`/`Write`; its `PermissionRequest` hook denies only deterministic policy violations. Devin's hooks check `edit`/`write`/`apply_patch` and return static findings as context without changing permission decisions. Copilot CLI gets documented `mcpServers` config, a plugin `sessionStart` context hook, and managed `preToolUse`/`postToolUse` hooks under `COPILOT_HOME` (or `~/.copilot`); the setup detects only same-event hook overlaps. The post hook covers `create`/`edit` and returns top-level `additionalContext`. Windsurf uses tested `pre_run_command`, `pre_read_code`, `pre_mcp_tool_use`, and `post_write_code` hooks; MCP calls are contract-checked without reading tool results, and post-write checks warn on Python/JSON syntax or high-severity invariant findings. Malformed or oversized pre-hook inputs fail closed per host contract. `agents.devin_plugin_route=true` selects the plugin MCP/skills route and skips a new standalone MCP entry; an existing entry is preserved and reported for reviewed cleanup. Plugin install state remains unprobed. Current host checks: Codex HTTP initialize and tools/list succeeded (seven tools); Claude and OpenCode previously listed Local AI Hub connected; Gemini, Antigravity, Cursor, Windsurf, and Devin CLIs are absent; Copilot shim says CLI is not installed. Live provider hook and plugin handshakes remain open.
- [ ] Make setup preview/apply/rollback preserve unrelated configuration and report partial/unsupported states. **Partial:** supported hook merges preserve unowned configuration; managed update staging includes `plugins/`. Tests verify all JSON MCP layouts (`mcpServers`, nested `mcp.servers`, and VS Code `servers`) plus Codex's managed TOML block roll back only the Hub entry while preserving unrelated servers/settings; Devin PreToolUse/PostToolUse cleanup preserves a user SessionStart hook; exact-byte whole-file rollback covers new Claude/Gemini/Cursor/Windsurf/Devin/Copilot hook configs; removal deletes only Hub event keys while retaining foreign hook events; Antigravity hook/script cleanup preserves custom settings; and update transaction failure cases restore staged `plugins/` payloads. A Windows newline-digest mismatch across whole-file hook ownership was fixed by recording on-disk bytes. Copilot operator edits are explicitly preserved. Live service update/rollback remains unverified.
- [x] Add per-provider status for configured, installed, enabled, trusted, connected, and runtime-verified states where observable.

## Task 4: Acceptance and documentation

- [x] Run focused checks for changed Hub decision paths, setup, MCP schemas, skills, manifests, and hook adapters. **Evidence:** this pass: `tests/test_provider_plugin_bundles.py`, `tests/test_antigravity_setup.py`, `tests/test_setup.py`, `tests/test_managed_host_hooks.py`, `tests/test_mcp_agent_routing.py`, `tests/test_mcp_stdio_handshake.py`, `tests/unit/test_antigravity_hook.py`, and `tests/unit/test_client_adapters_deep.py` — 256 passed, 1 symlink-platform skip. Prior Laya/provider runs remain historical and are listed above.
- [ ] Perform a real handshake for each available provider; keep unavailable host checks explicitly unverified. **Partial:** Codex HTTP MCP initialize/tools-list and Claude MCP connection were observed. No OpenCode Hub MCP, live Gemini/Antigravity/Cursor/Windsurf/Copilot host, or live provider hook/plugin execution was observed.
- [ ] Verify that one provider cannot obtain another provider's permissions or session identity. **Partial 2026-11-24:** provider headers resolve to the expected adapter; Laya decision and eligibility records now carry a normalized `provider_label` beside server-bound repository/task/session identity. The label is attribution only, not an authorization principal. Cross-provider session isolation and host permission non-transfer still need runtime acceptance.
- [x] Update docs and generated artifacts to match source capabilities and the active Laya behavior. With `[laya].enabled=true`, default mode resolves to advisory; validated, low-risk suggestions can affect eligible normal paths behind deterministic gates. This is not shadow-only. The pinned checkpoint is now cached and hash-verified; model-backed inference remains unverified.
- [ ] Record verification evidence per acceptance criterion; do not equate static checks with live host acceptance. **Partial:** see `docs/PROVIDER_INTEGRATION_MATRIX.md`; remaining runtime acceptance is listed above.

## Checkpoint — 2026-11-23

- Done: active-by-default Laya mode fallback and production-vs-shadow runtime gate separation, Codex plugin skills/onboarding and lifecycle hook bundle, Claude/Copilot hook paths, Antigravity invocation guidance and permission-preserving setup, native Antigravity/Claude/Copilot/Cursor plugin bundles, Gemini CLI extension, Cursor pre-shell policy hook, Windsurf policy-hook installer, provider status reporting, Copilot CLI native MCP config and `COPILOT_HOME`, and matrix documentation.
- Verified: focused Laya/provider tests: 137 passed before the second lifecycle test; Codex HTTP initialize/tools-list succeeded with seven tools; `claude mcp list` and `opencode mcp list` report Local AI Hub connected. Removed obsolete `laya.mode="advisory"` from user config and runtime overrides; current `load_config(probe_hardware=False)` succeeds with Laya enabled. The app now has a bounded, fail-closed shutdown path that keeps GPU services alive if Laya lease release is unconfirmed.
- Open: final combined safe focused test run; neural Laya checkpoint/device quality acceptance (pinned model is cached and all configured hashes are verified; actual model inference remains unverified); Hub plan MCP sync is deferred per user instruction and plan JSON must not be edited directly; runtime hook/plugin handshakes for absent providers; provider-isolation acceptance; semantic review (Hub review request failed before send; keep deterministic test/source evidence authoritative).

## Checkpoint — 2026-11-24

- Done: set `models.allow_hf_downloads=true` in both shipped defaults; updated model-download documentation and default tests. Corrected the pinned Laya tokenizer-config SHA-256 after the resolver rejected its malformed 66-character value; the downloaded pinned file's computed 64-character digest now matches the manifest.
- Verified: `tests/test_hf_model_download_opt_in.py` — 24 passed; bundle/schema set — 12 passed; provider identity + bundle set — 14 passed; update transaction rollback — 8 passed, 1 symlink-platform skip; combined focused Laya/provider set — 389 passed, 1 symlink-platform skip in 112.16s. The pinned Laya revision `e39264852ac9ba7c243ce33a0faa08eb647e54d4` is cached; resolver verified all five configured SHA-256 values. `config.runtime.toml` stores the resolved path, revision, and hashes. Effective HF downloads remain enabled; existing training-capture setting stayed unchanged. No training or rollout ran.
- Open: model-backed inference/device-quality acceptance; live provider hook/plugin handshakes where runtimes exist; provider-isolation acceptance; rollback spanning external provider config files. Hub plan synchronization was deferred per user request; do not use Hub unless user changes that instruction.

## Checkpoint — 2026-11-24 (continued without Hub)

- Done: corrected `plan-led-work` YAML frontmatter and synchronized it into six provider bundles; added Claude marketplace manifest and plugin author metadata. Claude marketplace validation passed. Registered `C:\Users\Adam\.local-ai-hub\plugins\claude` in Claude user settings and installed/enabled `local-ai-hub@local-ai-hub` in user scope; existing permission settings were not changed.
- Verified: `claude plugin validate plugins/claude` passed; `claude plugin list` shows Local AI Hub 6.1.0 enabled; marketplace points to the local checkout. `tests/test_provider_plugin_bundles.py` — 7 passed.
- Open: MCP/hook launch and provider isolation were not exercised, honoring the instruction not to use Local AI Hub in this task. Model-backed Laya inference/device-quality, live handshakes for other installed providers, and external-config rollback remain open.

## 2026-11-24 Provider MCP rollback evidence

- Verified: `tests/unit/test_uninstall_safety.py::test_provider_mcp_setup_rolls_back_only_hub_route` — 1 passed. In a temporary Cursor MCP config, setup added the Hub route and manifest ownership record; uninstall cleanup removed that route and preserved the unrelated `browser-mcp` server. This covers that JSON MCP path only; provider hooks and other config formats remain open.

## 2026-11-24 Windsurf hook fail-closed evidence

- Verified: `tests/test_managed_host_hooks.py` — 23 passed, 1 symlink-platform skip. Malformed and oversized Windsurf pre-hook payloads now return native blocking exit code 2; unsafe shell commands still block and clean commands still pass to Windsurf's own permission flow. No Windsurf runtime was launched.
- Newly identified provider gap: official Windsurf skills/hooks URLs now redirect to Devin Local documentation, which defines separate MCP, skills, rules, hook, and Agent Plugin layouts. The matrix records this drift; Devin-specific adapter, setup, and plugin packaging are not yet implemented.

## 2026-11-24 Devin Local provider integration

- Done: added default-enabled Devin Local provider identity/adapter, native MCP config path, global skill and rule routes, user-level `PreToolUse` hook setup, native `decision: block` output, and Agent Plugins 1.0 bundle. Devin malformed hook input blocks without granting permission. The setup-managed global route is distinct from the optional plugin bundle; automatic detection of the installed plugin route remains open.
- Verified: Devin hook/setup/adapter/plugin/MCP focused checks passed; wider setup/hooks/provider bundle/adapter/default set passed 120 tests with 1 symlink-platform skip. Provider MCP uninstall round-trip passed in the acceptance suite (3 passed); Devin hook ownership rollback passed (1 passed). Devin CLI is absent, so installation, trust, and runtime handshake remain unverified.
- Updated: added explicit `agents.devin_plugin_route` selection. Wizard selection skips duplicate global MCP and native skill setup, and setup reports stale standalone MCP for review. Plugin installation state remains host-controlled/unprobed.

## Checkpoint — 2026-11-24 (provider route deduplication)

- Done: Claude had both the new enabled plugin and an older user-scope MCP entry. Removed only the standalone `local-ai` server through `claude mcp remove --scope user`; plugin stays enabled. OpenCode had the same duplicate pattern. Confirmed its local plugin config includes its MCP launcher, then removed only the matching generated `local-ai` entry from `opencode.json`; kept a full backup at `C:\Users\Adam\.config\opencode\opencode.json.pre-plugin-dedupe-20261124` and preserved the unrelated server/config. Codex plugin was enabled alongside a standalone HTTP MCP with automatic tool approval; removed the standalone server with `codex mcp remove local-ai` so the plugin is the sole Hub route.
- Verified: native CLI reported successful Claude MCP removal. Plugin lists and config files were read-only checked; MCP processes were not started.
- Verified: setup now reports a manual action when OpenCode plugin setup finds the standalone `mcp.servers.local-ai` route too; it preserves both config entries instead of deleting unmanaged user data. New focused tests: 2 passed.
- Done: Codex setup recognizes its enabled plugin config and skips adding the duplicate standalone MCP route. Fresh standalone Codex MCP setup defaults to `prompt`; explicit existing approval choices remain unchanged.
- Verified: provider launcher parity, six provider MCP identities, Codex default approval, and Codex plugin detection — combined focused set: 17 passed. Official Codex plugin docs specify `default_tools_approval_mode = "prompt"` as the plugin policy example.
- Done: Claude setup recognizes the enabled plugin and avoids adding global MCP/hooks beside it. Removed two exact duplicate user-level Claude hook entries while preserving permissions and other settings; backup saved as `C:\Users\Adam\.claude\settings.json.pre-plugin-dedupe-20261124`.
- Verified: Claude plugin enabled, global duplicate hooks absent, unrelated permission settings unchanged; provider/setup/Codex focused set — 19 passed.
- Done: Antigravity's global MCP setup incorrectly labelled its provider identity `gemini`, which selected the Gemini CLI adapter. Corrected setup and refreshed the user's Antigravity config to `antigravity`; Gemini CLI settings retain `gemini`. Full config backup: `C:\Users\Adam\.gemini\config\mcp_config.json.pre-provider-identity-20261124`.
- Verified: three focused static Antigravity manifest/setup tests — 12 passed. No MCP process was started. Host has Antigravity app data, but no `agy` CLI or global plugin package; runtime/plugin verification remains open.
- Done: Gemini setup now checks native extension install/disabled state, and Antigravity checks its documented global plugin path. Both avoid adding global MCP/hooks beside plugin routes and report existing overlap; permissions and unmanaged settings remain preserved.
- Verified: Antigravity identity, Gemini/Antigravity plugin path and conflict fixtures, host manifest preservation — 15 passed. Current host has Gemini CLI global route, no Gemini extension path; Antigravity global route is correctly `antigravity`, and no global Antigravity plugin package is installed.
- Open: runtime launch, model-backed Laya acceptance, and provider isolation remain open. Other provider-specific plugin/MCP switches still need equivalent conflict detection.

## 2026-11-24 Antigravity native plugin

- Done: installed `plugins/antigravity/local-ai-hub` to `C:\Users\Adam\.gemini\config\plugins\local-ai-hub`. Backed up `mcp_config.json` and `hooks.json`, removed only the duplicate global Hub server and hook group, preserved all seven unrelated MCP servers.
- Verified: all 15 installed plugin files have identical SHA-256 hashes to the repository bundle; provider bundle/setup tests — 15 passed. No Hub MCP, hook, or Antigravity app was launched per user instruction.
- Open: host plugin/hook trust and runtime handshake, model-backed Laya quality, and provider-isolation acceptance remain unverified.

## 2026-11-24 Cursor native plugin

- Done: installed `plugins/cursor/local-ai-hub` under the documented local plugin directory. Backed up `~/.cursor/mcp.json`, removed only the matching standalone Hub server, and preserved `browser-mcp` and the existing user hook file.
- Done: setup now detects Cursor's local plugin manifest and avoids installing duplicate global Hub MCP or hooks; reports any existing global Hub route for manual cleanup.
- Verified: 15 installed plugin files match source SHA-256 inventory; Cursor/Gemini manifest and setup tests are included in the next targeted run. No Cursor app, MCP, or hooks launched per user instruction.
- Open: Cursor host trust/runtime handshake and cross-provider permission isolation remain unverified.

## 2026-11-24 Copilot route deduplication

- Done: setup reads Copilot CLI `enabledPlugins` from user settings and current repository Copilot/Claude settings, including local overrides. When Hub plugin is enabled, setup preserves and reports duplicate global MCP/hooks instead of adding another route.
- Verified: cursor/copilot/Gemini/Antigravity/Codex/Claude/OpenCode route conflict and provider bundle set — 23 passed. User/repository enablement precedence, duplicate-route preservation, and global fallback when plugin is absent are covered. Copilot CLI plugin listing confirms CLI unavailable on this host; plugin/runtime acceptance remains open.
- Open: Copilot host trust/runtime handshake, Laya model quality, and cross-provider permission isolation remain unverified.

## 2026-11-24 OpenCode route correction

- Done: OpenCode setup now writes to its documented user-global root (`~/.config/opencode`) or explicit `OPENCODE_HOME`; it no longer sprays configuration into `%APPDATA%\opencode` or user-root `.opencode` project config.
- Done: backed up the noncanonical AppData config and removed only its exact duplicate Hub plugin entry; preserved its MCP server settings and canonical OpenCode plugin configuration.
- Verified: OpenCode canonical/override path, provider route conflict, and provider bundle set — 24 passed. No OpenCode process or Hub runtime launched.
- Open: OpenCode runtime handshake and cross-provider permission isolation remain unverified.

## 2026-11-24 Active Laya route evidence

- Verified: typed Laya `model_route` advisory changes active pipeline from fast to smart/heavy; separate test proves model `fast` cannot downgrade deterministic `smart` baseline.
- Test: `python -m pytest tests/test_pipeline_tool_evidence.py::test_laya_advisory_route_changes_active_pipeline_model_tier tests/test_pipeline_tool_evidence.py::test_laya_fast_advisory_cannot_downgrade_smart_baseline -q` — 2 passed.
- Limit: uses a stubbed Laya response to verify application flow; real checkpoint inference/device quality remains unverified. No Hub runtime used.

## Review focus

- An Laya failure, malformed result, low confidence, or unsupported decision must preserve the deterministic route.
- A model suggestion must never grant permissions or trigger a host action by itself.

## 2026-11-24 setup entrypoint verification

- Fixed direct `tools/setup.py` invocation: add the repository root to `sys.path` before importing `tools.config_migrations`; script execution previously exposed only the `tools/` directory and failed with `ModuleNotFoundError: No module named 'tools'`.
- Verified: `tests/test_managed_host_hooks.py::test_setup_entrypoint_isolated_preview_apply_rollback` passed; focused provider/setup/hooks/plugin/adapter/uninstall/defaults batch passed — 138 passed, 2 skipped (Windows symlink privilege unavailable).
- Verified: `git diff --check` passed for the touched setup and integration-plan paths. Both packaged and root defaults retain `models.allow_hf_downloads = true`.
- Open: Laya checkpoint inference/device quality and live provider plugin/hook/MCP handshakes are unverified while Local AI Hub runtime use is paused by user instruction.

## 2026-11-24 truthful configuration diagnostics

- Fixed `tools/verify_agent_handshake.py`: JSON/config presence is reported as configuration, not a provider handshake; the local Hub `/ready` probe now requires explicit `--probe-hub`.
- TDD evidence: both new tests failed against the old behavior, then passed after the fix (`tests/test_verify_agent_handshake.py`: 2 passed). The Hub request was mocked in the opt-in test; no Hub runtime was contacted.
- Open: this utility still does not perform live provider-specific MCP handshakes; those require separate explicit host/runtime checks.

## 2026-11-24 active typed retrieval routing

- Fixed pipeline retrieval selection to use `evaluate_decision` with `category="retrieval_strategy"`, authorized evidence IDs, a deterministic hybrid baseline, and only installed backend options. Mapped `ast_graph`/`dense_rag` labels to the existing AST/semantic hybrid-weight strategies; no legacy heuristic recommendation now controls retrieval.
- Verified with red/green pipeline tests for all four labels and backend aliases plus the Laya and pipeline suites: 113 passed. The unavailable AST graph option is excluded when no code index exists; deterministic evidence alone does not prove that backend is available.
- Open: Laya model inference/device quality and real provider runtime acceptance remain unverified while Hub runtime use is paused.

## 2026-11-24 Windsurf post-write quality hook

- Added the documented `post_write_code` Cascade hook. Python/JSON files use the existing shadow compiler; syntax errors and high-severity invariant violations are surfaced as warnings without blocking Cascade. Unsupported file types pass through without reading file content.
- Setup merges the event into the existing user hook manifest and retains unrelated entries.
- Verified in isolation: Windsurf pre/post hook and setup regression selection — 6 passed; `git diff --check` passed. The shadow compiler was stubbed in hook tests; no shared-memory service, Local AI Hub runtime, or Windsurf host was launched.
- Official Windsurf docs list 12 Cascade events. Four have bounded Hub value and are wired: `pre_run_command`, `pre_read_code`, `pre_mcp_tool_use`, and `post_write_code`. `pre_user_prompt`, `post_cascade_response`, and `post_cascade_response_with_transcript` expose user or assistant conversation content; `post_mcp_tool_use` exposes MCP arguments/results; `post_read_code`/`post_run_command` are audit-only; `post_setup_worktree` would add environment/dependency side effects. `pre_write_code` supplies edit content but the documented payload does not give the hook a validated repo root for applying a Hub write policy. These events remain deliberately unbound pending a bounded need and safe input contract.
- Remaining: native Windsurf acceptance and live provider isolation are unverified. Source-level coverage of the four useful hooks is tested; no host runtime was launched.

## 2026-11-24 retrieval baseline validation

- Found and fixed a server-side allowlist gap: `evaluate_laya_decision` rejected the pipeline's `retrieval_strategy` baseline before inference because `hybrid_context_default` was not an accepted method.
- Red/green test now exercises the typed app validation path with a stubbed inference adapter and scoped evidence; `tests/test_laya_source_provenance_integration.py::test_typed_retrieval_advisory_accepts_pipeline_hybrid_baseline` passes. No Hub runtime or model inference was started.

## 2026-11-24 Devin plugin lifecycle coverage

- Updated the Devin Agent Plugin to include its documented root `hooks.json` with a non-blocking `SessionStart` context reminder. Kept the separately managed user `PreToolUse` policy hook to avoid duplicate enforcement and because Devin documents plugin hooks as best-effort/fail-open.
- Official Devin docs confirm plugins load root `hooks.json`, `SessionStart` supports `hookSpecificOutput.additionalContext`, and plugin hooks may fail open: https://docs.devin.ai/cli/extensibility/plugins/overview and https://docs.devin.ai/cli/extensibility/hooks/overview.
- Verified plugin bundle, selected route, and Devin policy hook suite — 37 passed, 1 Windows symlink skip. Executed the bundled SessionStart command in isolation and parsed its exact JSON context payload. No Devin CLI/plugin, hook host, or Hub runtime was started.

## 2026-11-24 provider-visible Laya source guidance

- Added shared skill instructions for active model/context/retrieval routing and the explicit `evaluate_context_source` operation, including aligned evidence IDs, task-scoped memory provenance, advisory-only effect, and unchanged host approvals.
- Propagated the canonical orchestrator skill to all seven provider plugin bundles and extended the live `local_ai_coord` tool description with the exact context-source contract.
- Verified: provider bundle parity, MCP descriptions, context-source consent, and Laya MCP contract suites — 52 passed. The forwarding test now isolates the task request from the separate tool-accounting request. `git diff --check` passed. No Hub runtime used.
- Provider hooks remain untrusted until the host owner reviews them; installing a skill/plugin does not prove hook trust.
- An MCP entry or installed skill is not proof of a successful runtime connection.
- Model training, benchmark generation, model download/publication, and broad rollout require their own existing authorization and quality gates.

## 2026-11-24 Antigravity and OpenCode projection parity

- Added distinct agent output profiles and provider-name normalization for Antigravity and OpenCode; mirrored the profile defaults in both TOML defaults files.
- Verified: focused projection, adapter registry, OpenCode adapter, provider bundle, Antigravity setup, and defaults consistency suites — 64 passed. Root and packaged defaults match; `models.allow_hf_downloads=true` in both.
- No Local AI Hub runtime or provider host was started. Live MCP/plugin/hook handshakes and Laya inference/device quality remain unverified.

## 2026-11-24 independent Antigravity setup

- Added `agents.antigravity` and independent setup wizard controls/status for Antigravity MCP and hooks; Antigravity-only selection now reaches setup with Gemini CLI disabled. Shared `.gemini/skills` and `GEMINI.md` stay shared because both hosts use those paths.
- Verified focused Antigravity setup tests: 3 passed; subsequent full Antigravity/setup/defaults/provider/OpenCode regression batch: 119 passed.
- No Hub runtime or provider host started.

## 2026-11-24 OpenCode route selection and Gemini CLI identity

- Exposed OpenCode provider setup and native-plugin-versus-standalone-MCP route in the setup wizard; standalone route selection honors `agents.opencode_plugin_route` even without wizard state.
- Added `gemini_cli` registry alias because the Gemini CLI extension advertises that exact `LOCAL_AI_AGENT` value; it now resolves to `gemini_cli` adapter.
- Verified: Antigravity/setup/defaults/provider/OpenCode regression batch — 119 passed; provider identity/adapters/OpenCode regression batch — 22 passed; latest defaults/manifest/adapter contract batch — 20 passed. Scoped `git diff --check` passed; root and packaged defaults match.
- A broad setup test initially wrote temporary hook commands into three real Antigravity profiles. Restored their hook files from matching pre-existing Hub backups and restored valid hooks to the stable interpreter; rechecked backup hashes and confirmed no temporary path remains.
- No Local AI Hub runtime or provider host started.

## 2026-11-24 provider identity authorization boundary

- Added provider-wide HTTP tests. `X-LocalAI-Agent` cannot authorize a remote admin request; loopback callers remain the one local owner for every provider label, with no provider-specific permission grant.
- Verified: `tests/unit/test_http_principal_selection.py` — 30 passed. Session scope continues to use explicit task/session IDs; runtime host-specific session behavior remains unverified.
- No Hub runtime or provider host started.

## 2026-11-24 default Laya checkpoint advisory gate

- Fixed `LocalAIServices.evaluate_laya_advisory`: default pinned Hugging Face config was rejected because the gate only accepted an explicit local `checkpoint_path`. It now accepts only an allowlisted repository with a pinned 40-character revision and non-empty hash manifest. Actual checkpoint resolution still enforces download consent and verifies hashes.
- Verified: default TOML advisory-gate test plus unallowlisted-repository rejection — 2 passed; gate and active pipeline regressions — 17 passed. No checkpoint resolution, model download, inference, or Hub runtime was executed.

## 2026-11-24 Claude post-tool static check

- Fixed the shared `PostToolUse` adapter to read Claude Code's native `tool_input` field; previously the hook ignored successful `Edit`/`Write` tool events because it only inspected `tool_args`.
- Added `PostToolUse` hooks to the Claude plugin and setup-managed settings for `Edit|Write`; the existing static check's syntax/high-severity findings return through Claude's documented `additionalContext` without changing permission decisions.
- Verified: Claude post-tool payload/context, setup ownership/idempotency, and plugin bundle contract — 6 passed. `git diff --check` passed. Static check was stubbed in hook tests; no Claude, Hub runtime, or MCP host launched.

## 2026-11-24 Cursor post-edit static check

- Added Cursor's documented `afterFileEdit` event to the native plugin bundle and setup-managed user hooks. The adapter normalizes Cursor's path-only payload into the shared post-tool static-check path; session and workspace roots remain validated, and no permission decision is produced.
- Updated Cursor capability metadata to report post-edit support alongside session and pre-action hooks.
- Verified: Cursor native event through the real hook CLI path, setup ownership/idempotency, bundle manifest, and adapter registry — 8 passed. `git diff --check` passed. No Cursor or Local AI Hub runtime was launched.

## 2026-11-24 Devin post-tool static check

- Added managed Devin `PostToolUse` hook for `edit`, `write`, and `apply_patch`; it reuses the shared static check and returns syntax/high-severity findings through documented `additionalContext`. No permission decision is made.
- Kept PreToolUse and PostToolUse as independently owned hook lists so setup preserves unowned user entries and rollback records the exact event key.
- Updated Devin adapter capability metadata to reflect pre/post tool coverage.
- Verified: Devin PostToolUse payload/context, explicit CLI event, setup ownership/idempotency, plugin bundle, and adapter registry — 10 passed. `git diff --check` passed. No Devin CLI, Hub runtime, or MCP host launched.

## 2026-11-24 Copilot post-tool static check

- Added a native Copilot `postToolUse` hook for `create` and `edit`, sharing the bounded static checker and returning findings via top-level `additionalContext` without affecting permission decisions.
- Setup still treats the Hub hook file as a single owned artifact; it preserves unowned files and records reversible ownership when available. VS Code/Copilot adapter metadata now includes pre/post tool hooks.
- Verified: Copilot native pre/post payload and CLI handling, reversible setup ownership, and adapter registry — 5 passed. Scoped `git diff --check` passed. No Copilot CLI, Hub runtime, or MCP host launched.

## 2026-11-24 provider hook rollback coverage

- Fixed whole-file hook ownership recording for Claude, Gemini CLI, Cursor, Windsurf, Devin, and Copilot to hash exact on-disk bytes after Windows newline translation. Uninstall now removes unedited Hub-created hook files.
- Devin hook rollback now verifies both managed `PreToolUse` and `PostToolUse` entries are removed while a user `SessionStart` hook remains.
- Verified the scoped rollback set — 9 passed, including preserving a user-edited Copilot file. Other provider configuration formats remain open; no Hub runtime or provider host launched.

## 2026-11-24 Laya provider attribution and shutdown

- Added a normalized transport provider label to typed Laya decisions and eligibility/decision telemetry, bound from server request context rather than the decision payload. It does not participate in authorization or model choice. Unrecognized callers map to `generic_mcp`.
- Fixed application shutdown to close the shared `execution_pool` after async work and before GPU/scheduler teardown.
- Verified focused decision, telemetry, candidate, runtime, and service suites — 249 passed; provider-header authorization boundary — 30 passed; scoped `git diff --check` passed. Hub/provider runtime was not started; live identity and model-quality acceptance remain open.

## 2026-11-24 mixed-provider hook rollback

- Added temporary-config uninstall coverage for Claude, Gemini CLI, Cursor, Windsurf, and Antigravity. It verifies owned hook entries/scripts are removed while pre-existing provider hooks and unrelated JSON configuration survive.
- The full targeted uninstall-safety suite and all 11 provider-label mappings passed — 37 passed, 1 symlink-platform skip. MCP/config rollback outside these hook formats remains open; no Hub runtime or provider host launched.

## 2026-11-24 active Laya route gates

- Rechecked the live pipeline path with stubbed advisory results: `smart` can upgrade the selected tier, `fast` cannot downgrade a smart baseline, and retrieval suggestions are restricted to available backends. The default pinned Hugging Face config remains eligible; unallowlisted repositories are rejected.
- Focused pipeline/advisory-gate checks passed — 9 passed. No model resolver, Hub runtime, or provider process was started.

## 2026-11-24 Windsurf hook coverage review

- Compared Hub coverage with Windsurf's documented 12 events. Kept the existing command/read policy hooks and post-write static check; intentionally left prompt/full-response capture and generic audit/side-effect hooks unbound because this integration has no approved retention or action policy for them.
- Updated Windsurf adapter capabilities to reflect both pre-action and post-edit coverage. Static source: https://docs.windsurf.com/windsurf/cascade/hooks.

## 2026-11-24 OpenCode provider attribution

- Fixed the OpenCode plugin MCP environment to identify both provider and profile as opencode, so typed Laya decisions/telemetry do not fall back to generic MCP attribution.
- Added focused assertions in the adapter config test. OpenCode documents JS execute.before/execute.after hooks; this plugin now registers a native post-edit hook and returns static findings as tool context; live handshake remains unverified under the user's no-Hub instruction.


## 2026-11-24 OpenCode native post-edit hook

- Registered OpenCode execute.after for successful file edits when the documented plugin hook API is available. The hook forwards only an absolute file path and session ID to the shared static check; it caps concurrent checks, timeout and output, confines checks to the project root, and adds findings as tool context without changing host permissions.
- Focused managed-hook/adapter tests: 41 passed, 1 platform skip. OpenCode plugin helper tests: 2 passed; Node syntax check and scoped diff check passed. OpenCode/Hub runtime was not launched per user instruction.


## 2026-11-24 Codex prompt hook

- Filled the existing Codex UserPromptSubmit hook with concise Hub/Laya guidance. It does not echo or persist the prompt and does not grant permissions; Codex still controls host approval.
- Official Codex hook reference confirms UserPromptSubmit supports hookSpecificOutput.additionalContext. Focused host-hook tests remain 41 passed, 1 platform skip; Node OpenCode helper tests 2 passed. No Hub or provider runtime was launched.

## 2026-11-24 Codex custom-install parity

- Codex MCP launcher already honored LOCAL_AI_HUB_DIR, but the plugin hook launcher skipped it and could resolve a different Hub. Hook resolution now follows the same explicit-install-first precedence and fails closed on an invalid explicit directory.
- Isolated Codex hook, provider hook, and OpenCode adapter tests: 43 passed, 1 platform skip. No Codex, Hub, or provider runtime was launched.

## 2026-11-24 Codex subagent context

- Added the documented SubagentStart lifecycle hook so child agents receive the same concise Laya/Hub advisory boundary as the root session. It reads no transcript, changes no permission, and caps injected context at 256 tokens.
- Codex hook bundle, custom-install launcher, managed host hooks, and OpenCode adapter checks: 55 passed, 1 platform skip after the context-limit assertions.

## 2026-11-24 OpenCode session context

- Added the documented session context hook. It injects concise Hub/Laya guidance only when a local_ai MCP tool is present, modifies only outgoing system instructions, and does not read history or change host permissions.
- OpenCode plugin helper tests: 3 passed; Node syntax check passed. Python provider/hook bundle tests: 55 passed, 1 platform skip. No Hub/OpenCode runtime launched.

## 2026-11-24 OpenCode instruction discovery audit

- Confirmed against OpenCode's current official docs that global skills load from `~/.config/opencode/skills` and the global instructions file loads from `~/.config/opencode/AGENTS.md`; setup writes both under the canonical config root or explicit `OPENCODE_HOME` override.
- No path correction needed. The skills and global instructions are installed by Hub setup alongside the native plugin, not bundled inside `plugins/opencode/local-ai-hub/`.
- Compared SHA-256 for the canonical `skills/local-ai-orchestrator/SKILL.md` and the Antigravity, Claude, Codex, Copilot, Cursor, Devin, and Gemini plugin copies; all eight files match exactly. OpenCode receives the canonical skill through setup's global skills directory.
- Static source/docs review only. No Local AI Hub, OpenCode host, or tests were run in this pass.
- Sources: https://opencode.ai/docs/skills/ and https://opencode.ai/docs/instructions/.

## 2026-11-24 provider MCP rollback schemas

- Added uninstall round-trip coverage for OpenCode's nested `mcp.servers` and VS Code's top-level `servers` schemas; both restore the original provider config while preserving unrelated MCP entries.
- Verified: `python -m pytest tests/unit/test_uninstall_safety.py::test_provider_nested_mcp_setup_restores_only_hub_route -q` — 2 passed. No Hub or provider runtime launched.

## 2026-11-24 provider route conflict regression audit

- Rechecked plugin/extension versus standalone MCP conflict handling for Codex, Antigravity/Gemini, Claude, Cursor, Copilot, Devin, and OpenCode. Setup preserves the existing duplicate route and reports manual cleanup instead of deleting unmanaged configuration.
- Verified in isolated setup tests: 10 passed across `tests/test_setup.py` and `tests/unit/test_codex_generator_prioritization.py`. No host process or Hub runtime launched.
- Remaining: live host plugin/MCP/hook trust and handshakes; cross-provider identity isolation under real provider sessions; Laya model inference/device quality. Extra MCP paths remain generic because their provider identity and host capabilities are not declared.

## 2026-11-24 Copilot plugin context hook

- Added Copilot CLI's documented Agent Plugins namespace hook at `com.github.copilot/hooks/hooks.json`. Its `sessionStart` injects only static Hub/Laya guidance; no prompt inspection or permission output. Kept managed global `preToolUse`/`postToolUse` checks because those events do not overlap.
- Made route conflict detection event-specific across Copilot user/repository settings and hook files (`.github/hooks`, `.github/copilot`, `.claude`, and `COPILOT_HOME/hooks`). Setup skips duplicate tool events, installs missing ones, and preserves/reports unowned files.
- Verified: targeted plugin-bundle and Copilot setup route tests — 9 passed. No Copilot, Hub, or provider hook runtime launched. Official docs: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference and https://docs.github.com/en/copilot/reference/hooks-reference.

## 2026-11-24 VS Code workspace MCP apply

- Corrected the VS Code MCP generator to emit the documented `servers` root and explicit `type = "stdio"` entry; added `hubctl client config --client vscode --apply --root <workspace>` for an explicit workspace-scoped merge that preserves unrelated servers and writes a backup. If the Hub install ownership manifest is present, the apply also records exact rollback ownership; JSON reports `rollback_tracking` as `install_manifest` or `backup_only`.
- `--apply` requires both the VS Code client and an explicitly supplied `--root`; configuration generation remains read-only. No Hub/provider runtime is started.
- Verified: focused hubctl VS Code config/apply and OpenCode config tests — 4 passed. An earlier targeted run failed as expected before implementation (3 failures).

## 2026-11-24 VS Code apply rollback ownership

- Closed the remaining explicit-apply rollback gap: VS Code workspace MCP apply now temporarily binds the current Hub install ownership manifest while merging, validates the manifest first, and restores setup's prior owner context afterward. A foreign/unowned conflicting server entry is rejected on read-back instead of being reported as applied.
- Verified real in-process apply -> ownership record -> uninstall restore in a temporary workspace; targeted VS Code and provider-schema uninstall checks — 5 passed. Without an install manifest, a timestamped backup remains and output labels the route `backup_only`.

## 2026-11-24 visible active Laya defaults

- Made `config.toml.example` explicitly show Laya enabled as active typed advisory routing and Hugging Face checkpoint downloads enabled; added regression assertions for example and shipped defaults, including rejection of the retired `laya.mode` setting.
- Focused defaults/lifecycle validation — 4 passed. This proves configuration defaults only; model inference and device quality remain unverified under the no-Hub instruction.

## 2026-11-24 Gemini CLI extension hook schema

- Corrected `plugins/gemini/local-ai-hub/hooks/hooks.json`: Gemini hook event values are arrays of hook groups, matching the current native schema. The prior object form parsed as JSON but failed the provider schema.
- Tightened the bundle test to verify event arrays/groups and the extension path; the regression test failed before the source fix, then the provider bundle plus Gemini setup-route checks passed — 13 passed.
- Source: https://geminicli.com/docs/hooks/reference/ and https://geminicli.com/docs/extensions/reference/. No Gemini, Hub, or provider runtime launched.

## 2026-11-24 Gemini session context

- Gemini CLI's `SessionStart` hook previously performed repository warmup but returned no context. It now injects a short static instruction to use typed Laya advice for bounded decisions while keeping deterministic validation and host permissions authoritative.
- The handler retains only bounded session/root fields; the regression test includes fake prompt/transcript markers and confirms neither is returned. Focused host-hook, bundle, and Gemini route checks — 16 passed.
- Source: https://geminicli.com/docs/hooks/reference/ (`SessionStart` supports `hookSpecificOutput.additionalContext`). No Gemini or Hub runtime launched.

## 2026-11-24 Antigravity hook contract audit

- Compared the native bundle with Google's current Antigravity plugin contract: named hook group, flat `PreInvocation` handlers, matcher-wrapped tool events, plugin-relative commands, and the `injectSteps` context response. The bundle follows this shape; clarified a stale module docstring and strengthened static bundle assertions for the contract.
- Focused native-bundle, PreInvocation-context, and setup idempotency checks — 3 passed. `git diff --check` passed. No Antigravity CLI/app, Hub runtime, or MCP host launched.
- Source: https://antigravity.google/docs/build-plugins/.

## 2026-11-24 Laya task guidance and provider attribution

- Added an active `next_step` typed advisory to ordinary pipeline results. The route metadata is bounded by verified evidence, only offers `run_test` when deterministic impact lists tests, and adds `ask_human` for high/critical risk; it never launches tools or changes task state.
- Provider-attribution follow-up: Laya now resolves stdio MCP identity from provider-scoped `LOCAL_AI_AGENT` when no HTTP request context exists; active HTTP identity remains authoritative. All seven portable launchers now default missing provider identity to `generic_mcp` rather than falsely claiming Antigravity.
- Verified offline: `python -m pytest tests/test_pipeline_tool_evidence.py -q` — 17 passed; combined Laya attribution/provider bundle set — 41 passed; `git diff --check` on changed source/test files passed. No Hub, MCP endpoint, provider host, or neural inference ran; live handshakes and device-quality acceptance remain open.

## 2026-11-24 provider MCP rollback layouts

- Expanded install-manifest rollback acceptance across the JSON MCP providers and schemas: `mcpServers` (Antigravity, Claude, Copilot, Cursor, Devin, Gemini CLI, Windsurf), nested `mcp.servers` (OpenCode), and VS Code `servers`. Each check proves uninstall removes only the Hub route and preserves the unrelated server and original config.
- Added a Codex TOML ownership round-trip through `codex_mcp_merge` and the real external-config cleanup path. It checks the local-ai managed block is removed while model selection and foreign MCP settings survive.
- Verified: three focused MCP rollback tests — 10 passed. Live update/rollback transaction acceptance remains open; no provider runtime or Hub was started.

## 2026-11-24 provider package update transaction

- Rechecked staged update and install-candidate rollback coverage for the provider `plugins/` tree. Existing failure tests cover staging-copy failure, payload swap failure, activation/migration rollback, and preservation of the installed payload plus user state/runtime files.
- Verified: `python -m pytest tests/unit/test_update_transaction.py tests/test_update_install.py -q` — 17 passed, 1 Windows symlink-privilege skip. This is offline transaction coverage; a live service stop/swap/restart was not run.

## 2026-11-24 provider regression audit correction

- A broad provider test selection accidentally included `tests/test_mcp_stdio_handshake.py`; it spawned MCP server subprocesses, which failed initialization because test install configs lacked `config_schema_version = 1`. Two leftover server processes were stopped. No handshake passed, and these failures are not acceptance evidence.
- The same run found `test_vscode_mcp_config` asserted the retired `mcpServers` root although the adapter correctly generates VS Code's `servers` root. Updated the test to the documented schema; verify this isolated static adapter case only. Do not rerun MCP handshake tests under the user's no-Hub instruction.
- The safe provider-only set later returned 176 passed, 1 symlink skip, 1 failure at warnings-as-errors in `test_skip_service_uses_hubctl_fallback_without_managed_service` due two unclosed SQLite connections. The failing fixture uses a temporary install and mocks service commands; process inspection found no Local AI Hub process afterward. The warning's originating test remains unknown.
- Fixed launcher attribution precedence: explicit `host_hooks --host <provider>` now sets both `LOCAL_AI_AGENT` and `LOCAL_AI_AGENT_PROFILE` over conflicting inherited values. The provider bundle suite uses a captured `execve` to check all seven copies without launching Hub; `tests/test_provider_plugin_bundles.py` — 18 passed.

## 2026-11-24 Gemini native consent policy

- Added Gemini extension Policy Engine rules asking for host confirmation on coordinator actions that release GPU resources, delete or archive state, clean/reap worktrees or sessions, repair tasks, change budgets, or complete with an operator waiver. Hub consent, ownership, and evidence checks remain authoritative.
- Verified policy TOML parsing and representative argument matching through `tests/test_provider_plugin_bundles.py` — 19 passed; scoped `git diff --check` passed. No Gemini, Local AI Hub, MCP server, or inference runtime was launched.
- Official native contract: https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md and https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/policy-engine.md. Host install/trust and actual approval prompts remain unverified.

## 2026-11-24 Windsurf MCP pre-hook

- Added Windsurf's native `pre_mcp_tool_use` event. It validates calls to the configured `local-ai` MCP server with the same operation contract used by the server; malformed and unknown Hub calls block, valid calls pass without granting permission, and unrelated MCP servers are untouched. Hook does not inspect MCP results or conversation text.
- Setup installs the event reversibly with existing Windsurf hooks. Focused hook/setup checks — 2 passed; scoped `git diff --check` passed. No Windsurf, Hub, or MCP runtime launched.
- Contract: https://docs.windsurf.com/windsurf/cascade/hooks. Live hook delivery remains unverified because Windsurf is absent and Hub runtime use is paused by user instruction.
- Extended verification covers temporary setup, unrelated MCP calls, invalid Hub call blocking, rollback of another user-owned event, and fail-closed same-event collision preservation — 7 passed. Existing same-event user hooks are not merged automatically; setup requests manual merge instead.

## 2026-11-24 Claude subagent context hook

- Added Claude Code's native `SubagentStart` event to the shared host hook handler and plugin bundle. The hook supplies only bounded static Laya guidance; it does not read prompt text, transcript, or task content. Global setup installs it reversibly and preserves unowned same-event lists for manual merge.
- Claude `SessionStart` also gets the same static Laya guidance. Its test stubs repository warmup, so the test makes no Hub request.
- Verified offline: focused Claude hook, setup, uninstall rollback, and plugin-bundle checks — 6 passed, 4 deselected. `git diff --check` pending. No Local AI Hub, MCP server, or provider runtime launched.
- Native contract: https://code.claude.com/docs/en/hooks. Plugin/global route conflict and live hook delivery remain unverified on host.

## 2026-11-24 distinct Copilot Laya attribution

- Kept the shared VS Code adapter for Copilot formatting/capabilities, but stopped collapsing Copilot into VS Code in Laya's provider attribution. HTTP identity headers and stdio `LOCAL_AI_AGENT=copilot` now record `copilot`; VS Code remains `vscode`. Attribution remains diagnostic metadata, never an authorization principal.
- TDD evidence: updated HTTP and stdio identity expectations first; both failed with actual `vscode` versus expected `copilot`. After the minimal attribution fix, the complete normalized-header, stdio, concurrent request-scope, and canonical-request identity set passed — 22 passed. `git diff --check` passed. No Hub/MCP/provider runtime launched.
- Host-level permission isolation and live Copilot handshake remain unverified.

## 2026-11-24 provider skill acceptance alignment

- The provider-bundle suite encoded an obsolete shadow/profile-neutral expectation: it required Laya active routing to be absent even though the canonical skill now describes active gated Laya use. The provider snapshots already byte-match canonical skills; root cause was stale test intent, not missing bundle content.
- Replaced that contradictory assertion with checks that every provider snapshot retains active Laya guidance, declares live `tools/list` authoritative, and gates `local_ai_work` by profile capability and explicit delegation. Provider bundle suite — 20 passed. No MCP, Hub, or provider runtime launched.

## 2026-11-24 provider rollback and native setup regression

- Revalidated provider uninstall ownership with temporary config fixtures: `tests/unit/test_uninstall_safety.py` — 37 passed, 1 Windows symlink privilege skip. Hub MCP entries and hook cleanup preserve unrelated servers/events and user-edited files.
- Revalidated Antigravity setup, hook contract, and Codex setup prioritization — 33 passed; Codex custom-install/fail-closed plugin launcher checks — 2 passed. Tests used isolated fixtures; no Hub MCP service or provider host launched.
- Remaining acceptance unchanged: Laya model inference/device quality, live provider MCP/plugin/hook handshakes, and cross-provider host permission isolation.

## 2026-11-24 provider route and hook setup regression

- Revalidated plugin-versus-global route selection, duplicate preservation, native MCP schemas, and isolated hook installation for Codex, Antigravity, Claude, Gemini CLI, Cursor, Windsurf, Copilot, Devin, and OpenCode. The selected setup-only set passed — 50 passed. The service-start test was excluded; no Hub or provider runtime launched.
- Setup does not overwrite conflicting user routes or unowned hook events; it reports manual cleanup/merge where ownership is absent. Live trust prompts and provider hook delivery remain unverified.

## 2026-11-24 pinned Laya checkpoint integrity recheck

- Read only the pinned runtime config fields. The configured cache directory resolves to revision `e39264852ac9ba7c243ce33a0faa08eb647e54d4`; all five pinned SHA-256 values match current files, including `model.safetensors` (643,835,524 bytes). `models.allow_hf_downloads=true` is present in active runtime config and both shipped defaults.
- This verifies local artifact integrity, not compatibility, inference quality, hardware routing, or device performance. No Local AI Hub, model runtime, or provider host launched.
- Rechecked active-path behavior offline: default pinned-checkpoint advisory gate, rejection of an unallowlisted repository, model-tier application, typed retrieval application, non-executing next-step guidance, smart-baseline floor, and Laya gateway routing — 12 passed. This proves deterministic integration gates, not neural inference quality.
- Claude's native CLI validated both marketplace root and plugin bundle manifests after adding `SubagentStart`. These are package/schema validations only; no Claude MCP connection, hook delivery, or Hub runtime was started.
- Current command inventory: Codex, Claude, OpenCode, and the Copilot shim are present; Gemini CLI, Antigravity, Cursor, Windsurf, and Devin are absent. OpenCode plugin's pure JavaScript hook/Laya-context suite — 3 passed. No provider host was launched.
- Codex CLI help exposes plugin add/list/remove/marketplace commands, no native validate command. Verified its packaged manifest/MCP/hooks, setup projection, and fail-closed custom-install launcher through isolated tests — 4 passed. No plugin or Hub was launched.

## 2026-11-24 OpenCode JSONC route deduplication

- Implemented fail-closed JSONC parsing for OpenCode configuration inspection, including comments, trailing commas, string-safe comment handling, and BOM input. Setup now detects standalone `local-ai` MCP routes in both `opencode.json` and `opencode.jsonc`; when one exists, it preserves the selected user route and reports the duplicate instead of adding a second plugin/MCP route.
- Verified offline: targeted OpenCode setup selection/deduplication tests — 7 passed; OpenCode plugin JavaScript tests — 3 passed; `git diff --check` passed. No Hub or provider runtime launched.
- Read-only host config check finds standalone Hub MCP in `%USERPROFILE%\\.config\\opencode\\opencode.jsonc`; `%USERPROFILE%\\.config\\opencode\\opencode.json` also registers the Hub plugin. The JSON file additionally contains a `scan2cad` MCP command pointing into a pytest temporary directory. External config remains untouched pending clear ownership; live provider handshake not run.

- Host config cleanup: backed up %USERPROFILE%\.config\opencode\opencode.jsonc and removed only the duplicate local-ai MCP entry; verified the plugin route remains registered and rowser-mcp plus the Hub skills path are preserved. No Hub or OpenCode runtime launched.


## 2026-11-24 Codex hook coverage boundary

- Audited the current Codex hook contract against the packaged Hub plugin. The five integrated events remain `SessionStart`, `UserPromptSubmit`, `SubagentStart`, `PreToolUse`, and `PostToolUse`; additional documented hooks either participate in host consent or expose prompts/model requests/transcripts, and do not add a required Laya capability under the current privacy contract.
- Recorded the intentional boundary in the provider matrix. No additional Codex event was enabled; no Hub, Codex MCP, or hook runtime launched.

## 2026-11-24 default provider-to-adapter audit

- Compared the nine default-enabled provider identities against setup-wizard choices and the live adapter registry. All nine resolve to a provider-specific adapter; Gemini maps to `gemini_cli`, Copilot to the shared `vscode` adapter while retaining a distinct `copilot` attribution label. Windsurf's adapter is registered from the shared Cursor/Windsurf module.
- Registry and provider plugin-bundle tests — 25 passed. No MCP server, Hub runtime, or provider host was launched.

## 2026-11-24 provider report state separation

- Closed the setup-report gap from acceptance criterion 6. `provider_integration` now has a provider-level `configured` summary plus separate `installed` and `enabled` fields. The latter remain explicitly `not_observed_by_setup`; trust, connection, and runtime verification keep their separate host-controlled/unknown states.
- Red/green evidence: the new setup-report contract test first failed because `configured` was absent; after the change, the two provider-report tests passed. JSON serialization is covered. No provider or Hub runtime was started.

## 2026-11-24 provider setup outcome attribution

- Fixed a per-provider reporting defect: previously one manual step or one batch exception could mark every selected provider `configured_with_manual_steps` or `failed_or_partial`. Setup now attributes a manual action only when its text identifies exactly one provider; unmatched or ambiguous actions stay in a separate report list. A failed batch marks selected routes outcome-unknown, not failed.
- Red/green tests first failed on missing provider action attribution and batch-error scope. Final provider-report tests: 4 passed; `py_compile` and `git diff --check` passed. No Local AI Hub or provider runtime launched.

- Shared Gemini/Antigravity instruction warnings now identify every selected owner. The action map applies shared-path warnings to both named providers and leaves unknown actions unattributed. A test exposed the old one-provider-only behavior; focused Gemini/Antigravity and provider-report set passed — 29 passed. No Hub or provider runtime launched.

## 2026-11-24 OpenCode handshake-config verification

- Corrected `verify_agent_handshake.py` to honor canonical OpenCode global config and `OPENCODE_HOME`, inspect both JSON and JSONC, and report whether a Hub plugin or standalone MCP route is present. Removed stale `%APPDATA%` and `~/.opencode` probing from this verifier; it still does not claim a live handshake.
- Red/green acceptance: explicit-home JSONC test failed before the change, then verifier and OpenCode JSONC regression selection — 6 passed. `py_compile` and `git diff --check` passed. No Hub, MCP server, or OpenCode runtime launched.

## 2026-11-24 OpenCode JSONC plugin route deduplication

- Setup now detects existing Hub plugin registrations in both `opencode.json` and `opencode.jsonc`. Plugin route selection preserves a plugin already present in either file; standalone route selection preserves an existing plugin instead of adding duplicate MCP tools. JSONC parsing remains comment/string safe and malformed config fails closed.
- Red/green evidence: both new route tests failed before the change. Combined JSONC plugin/MCP route selection and verifier coverage — 8 passed; py_compile and diff checks passed. Read-only host check finds the Hub plugin in `opencode.json` and no standalone route; no OpenCode or Hub runtime launched.

## 2026-11-24 Static provider route report

- `verify_agent_handshake.py` now checks direct `local-ai` MCP route entries in provider JSON configs and Codex TOML. Valid config without that route reports `CONFIG_PRESENT_NO_HUB_ROUTE`; malformed config remains distinct. OpenCode plugin detection remains a configuration observation, not a live handshake.
- Focused verifier suite: 4 passed; `py_compile` and scoped `git diff --check` passed. No Local AI Hub, MCP, Laya, or provider runtime launched. Live inference, activation, trust, permissions, and handshakes remain open.

## 2026-11-24 Codex and Claude plugin config reporting

- Static host inspection found Codex's `plugins.local-ai-hub@local-ai-hub.enabled=true` in `config.toml` and Claude's matching `enabledPlugins` flag in `.claude/settings.json`; the earlier verifier only searched for standalone MCP entries and therefore underreported both integrations.
- Added separate `PLUGIN_ENABLED_CONFIGURED` reporting. It does not assert plugin package installation, host trust, or runtime activation. Red/green fixture test passed; verifier suite — 5 passed; `py_compile` and scoped `git diff --check` passed. The no-flag verifier run read configuration only and skipped Hub readiness. No Hub, MCP, or provider runtime launched.

## 2026-11-24 Antigravity plugin manifest reporting

- The host has `~/.gemini/config/plugins/local-ai-hub/plugin.json`, but the verifier checked only `mcp_config.json` and falsely reported no configured Hub route. Added a distinct `PLUGIN_MANIFEST_PRESENT` state after validating the manifest identity; it does not claim Antigravity is installed, trusted, or running.
- Red/green fixture test passed. Verifier suite — 6 passed; `py_compile` and scoped `git diff --check` passed. Static verifier shows Antigravity manifest, Gemini CLI MCP, Codex/Claude plugin config, Windsurf MCP, and OpenCode plugin config. Hub readiness remains skipped; no runtime launched.

## 2026-11-24 current offline acceptance rerun

- Re-ran the active Laya decision gates, pipeline evidence/provenance, and provider plugin bundle fixtures against the current checkout: 55 passed. This verifies mocked/fixture integration paths for model routing, context/retrieval guidance, next-step metadata, and provider bundle consistency; it is not neural inference or a live provider handshake.
- No Hub service, MCP server, Laya model, or provider host launched.

## 2026-11-24 Cursor plugin manifest reporting

- Current host has Cursor's native plugin at `~/.cursor/plugins/local/local-ai-hub/.cursor-plugin/plugin.json`; the route verifier previously checked only `~/.cursor/mcp.json` and reported no Hub route. Generalized manifest identity validation and added the Cursor native plugin path as a separate `PLUGIN_MANIFEST_PRESENT` observation.
- Red/green fixture test passed; verifier suite — 7 passed; `py_compile` and scoped `git diff --check` passed. Static output now recognizes native plugin manifests for Antigravity and Cursor. No host, MCP, or Hub runtime launched.

## 2026-11-24 subagent budget decision path

- Found `DecisionCategory.SUBAGENT_BUDGET` had closed options/instructions but no deterministic baseline or runtime capture method, so the typed evaluator necessarily rejected it. Added a linked-evidence baseline `agent_os_delegation_budget=single_agent`, registered it for runtime verification/capture, and documented the optional MCP advice as metadata that never launches agents or bypasses existing delegation gates.
- Red/green baseline/registry/capture tests passed. Safe offline Laya/service/candidate/provenance/tool-description suites — 157 passed; `py_compile` and scoped `git diff --check` passed. `tests/test_laya_mcp_contract.py` was excluded: importing it loads `mcp_server`, whose `HubClient(auto_start=True)` initialization rejected the repository `config.toml` for lacking `config_schema_version=1` before starting a service. No Hub runtime was started.

## 2026-11-24 provider integration suite rerun

- Provider setup, Antigravity, managed-hook, and plugin-bundle selection — 187 passed, 1 symlink skip, 1 failure. The failure is pytest teardown elevating two unclosed SQLite `ResourceWarning`s in the mocked `test_setup_starts_hub_before_configuring_http_mcp[False-True]`; its `install_persistent_service` and command runner are stubs, so it did not start/restart Hub. No other provider test failed.
## 2026-11-24 Gemini BeforeAgent lifecycle integration

- Official Gemini CLI hook reference documents `BeforeAgent` as a prompt-bearing event. The shipped handler already normalized it while dropping prompt and transcript fields, but the native extension did not register it and the handler returned no Laya guidance.
- Added the extension registration and static per-request Laya/MCP context. Added `hookEventName` required by the native hook-specific output shape. The handler consumes only bounded session and repository identity; the prompt marker is not returned or persisted.
- Red/green regression: new handler test failed before implementation; focused managed-hook and provider-bundle suite now passes — 64 passed, 1 Windows symlink skip. `py_compile` and scoped `git diff --check` passed. No Hub service, MCP server, Laya model, or provider host launched.
- Provider event audit: retain Codex permission/request/transcript/model hooks as deliberate omissions unless a bounded need exists; permission decisions stay with the host, and prompt/model/transcript-bearing events are not wired for content inspection. Gemini `BeforeAgent` is safe because the adapter strips event content before producing static guidance.

## 2026-11-24 Claude UserPromptSubmit lifecycle integration

- Claude's native prompt-submission hook supports static additional context. Added it to the plugin bundle and reused the host hook's existing `UserPromptSubmit` route.
- The handler emits advisory Laya/MCP guidance only: no permission decision, prompt echo, persistence, or Hub/model call. The hook receives the native event payload but does not inspect the prompt field.
- Red/green regression failed before implementation and passed after. Managed-hook and provider-bundle suites: 65 passed, 1 Windows symlink skip. `py_compile`, JSON parsing, and scoped diff check passed. No Hub service, MCP server, Laya model, or provider host launched.

## 2026-11-24 Antigravity lifecycle event boundary audit

- Rechecked the official Antigravity hook contract. `PreInvocation` receives `lastUserInput` and a transcript path; injected steps persist in the conversation. `PostInvocation` and `Stop` expose response/execution-control surfaces. Keep the plugin on `SessionStart` plus bounded tool hooks rather than repeatedly injecting content-bearing model hooks.
- Confirmed `PreToolUse` output `decision: allow` delegates to later hooks/default policy. It does not auto-approve; only `auto_approve` bypasses a default prompt (while still honoring explicit user rules). Existing adapter does not emit `auto_approve` or permission overrides.
- This was an official-documentation/static-source audit only; no test or host runtime was needed or launched.

## 2026-11-24 Claude Windows shell hook coverage

- Official Claude Code docs note that PowerShell is the primary shell on Windows when Git Bash is unavailable. The Claude `PreToolUse` matcher covered only `Bash|Read`, so shell policy was skipped for native PowerShell calls.
- Updated both the native plugin bundle and setup-generated global hook matcher to `Bash|PowerShell|Read`. Existing event normalization and deterministic tool policy already handle PowerShell command arguments.
- Red/green: plugin, setup-generation, and host-approval preservation tests failed before the matcher change and now pass — 3 passed. `py_compile`, JSON parsing, and scoped `git diff --check` passed. No Hub service or provider runtime launched.

## 2026-11-24 Gemini extension route verification

- The static provider verifier checked Gemini CLI `settings.json` MCP entries but omitted the native extension install path, so it could miss the packaged Hub extension route.
- Added detection for `~/.gemini/extensions/local-ai-hub/gemini-extension.json`, validating its `name` and reporting `EXTENSION_MANIFEST_PRESENT`. This reports installed files only; it does not claim the extension is enabled, trusted, or connected.
- New verifier test failed before the change; the full verifier suite now passes — 8 passed. `py_compile` and scoped diff check passed. No Hub readiness request was made.

## 2026-11-24 Active Laya pipeline and MCP wrapper audit

- Current source confirms Laya is not wired as shadow-only: `LocalAIServices.evaluate_laya_advisory` validates the pinned route and typed evaluator result; the ordinary pipeline applies eligible `model_route`, `retrieval_strategy`, `context_budget`, and non-executing `next_step` suggestions behind deterministic gates. `defaults.toml` sets `[laya].enabled=true`. Fixture acceptance: the two-file Laya advisory/pipeline suite yielded 18 passes and one unrelated failure; all Laya route/retrieval/context/next-step cases passed. No model inference was invoked.
- The unrelated failure exposed `local_ai_repo` forwarding a redundant `file=` keyword to `_local_ai_repo_impl`; the public wrapper already normalizes `file` into `path`. Removed only the redundant forwarded keyword. The failing test imports `mcp_server` but replaces `CLIENT.post` before use; `HubClient(auto_start=True)` does not start on construction, so no request or Hub service was invoked.
- Because the user asked not to use Local AI Hub, the behavioral test was not rerun after the fix. Source-only AST delegation check now proves the wrapper's 43 positional and 28 named arguments match the internal signature; `py_compile` and scoped diff check pass. This is static evidence, not post-fix runtime acceptance.

## 2026-11-24 wrapper delegation regression guard

- Added an AST-only regression test for the public `local_ai_repo` wrapper. It verifies forwarded positional and keyword arguments against `_local_ai_repo_impl` without importing `mcp_server` or invoking Hub runtime.
- `python -m pytest tests/test_mcp_tool_delegation_signatures.py -q`: 1 passed. `py_compile` and scoped `git diff --check` passed. No Local AI Hub service, MCP server, provider host, or Laya inference was started.

## 2026-11-24 Codex PermissionRequest integration

- Current Codex hook docs expose `PermissionRequest`, omitted from the previous hook matrix. Added it to the Codex plugin and project-local registrations for Bash/patch approval requests.
- The handler reuses the bounded deterministic policy and can only return a native Codex deny for a violation. It returns no decision for safe/unknown requests, never approves, and leaves the ordinary Codex approval prompt authoritative.
- Red/green hook regression passed after implementation. Project-local registration and denial tests: 3 passed; Codex plugin bundle test: 1 passed. Python compilation, JSON parse, and scoped diff check passed. No Hub service, MCP server, Codex host, or Laya inference was started.
- Updated the provider matrix with the full documented Codex event surface and explicit reasons remaining content-bearing or flow-control events are not wired.

## 2026-11-24 Devin Local plugin platform boundary

- Official Devin plugin docs say `platforms` defaults to all surfaces; the bundled plugin starts a local stdio MCP process and is specifically for Devin Local. Added `platforms: ["local"]` so it is not offered to Devin cloud sessions where the local launcher cannot be available.
- Added the platform-boundary assertion first; it failed on the previous manifest, then passed after the manifest change. Devin bundle test: 1 passed. JSON parsing and scoped diff check passed. No Devin, Hub, or MCP runtime launched.

## 2026-11-24 OpenCode optional work tool

- The OpenCode client adapter removed `local_ai_work` from the MCP server tool catalog unconditionally, so its plugin could never surface Hub's bounded delegation tool even when the server's live feature/schema gates enabled it.
- Added `local_ai_work` to the adapter capability allowlist and OpenCode guidance. The JS plugin now requires the six core tools but includes work only if the live `tools/list` schema advertises it; the Hub remains responsible for feature, authorization, and explicit-delegation checks. Updated the existing client-status expectation.
- Red/green regression passed after the implementation. OpenCode JS plugin tests: 4 passed; Python adapter/filter tests: 4 passed. The client-status MCP test was not run because it imports the Hub MCP server; no Hub or MCP runtime started.

## 2026-11-24 provider hook capability inventory

- Added `hook_events` to adapter capability reports and the `client_status` result allowlist. Codex, Antigravity, Claude, Gemini CLI, Cursor, Windsurf, VS Code/Copilot, Devin, OpenCode, and generic MCP now report the exact native event identifiers wired by their supported integration path.
- Claude's plugin and global setup gained deny-only `PermissionRequest` support; it reuses the deterministic tool policy and returns no decision for safe or unknown requests. Native event/output schema was checked against current Claude Code hook docs.
- Added uninstall coverage for Claude's new `PermissionRequest` hook: a newly created settings file is removed, and a pre-existing foreign `SessionStart` hook survives cleanup. The focused provider-hook rollback parametrizations passed — 12 passed.
- Shared orchestrator skill now documents active typed Laya advice, task-scoped context-source provenance, and live MCP schema authority; provider copies were synchronized.
- Offline adapter and provider-hook suites: 13 passed and 69 passed, one Windows symlink skip. A source-only AST guard for the `client_status` projection allowlist passed — 2 passed; it does not import `mcp_server`. Python compilation and scoped diff checks passed. One early test selection accidentally included `tests/unit/test_mcp_client_status.py`, which imports the MCP server; a later process inspection found no Hub/MCP process running. Do not count that test as permitted acceptance evidence. No Laya inference or provider host was launched. Continue to avoid MCP-server imports and runtime checks while the user says not to use Hub.

## 2026-11-24 OpenCode permission.evaluate

- Official OpenCode plugin docs confirm V2 `permission.hook("evaluate")` can change an allow/ask result to deny before action execution. The plugin now sends bounded shell resources to the existing deterministic command policy and applies deny only; safe or unrecognized commands retain OpenCode's configured permission flow.
- OpenCode adapter capability metadata and provider matrix now include `permission.evaluate`. Payloads contain only the bounded command and session/root metadata; prompt or transcript content is not forwarded.
- Focused offline verification: OpenCode host hook selection — 5 passed; JS plugin suite — 5 passed; adapter suite — 3 passed; Python compilation and scoped `git diff --check` passed. A follow-up hardening change checks all bounded shell resources from a permission event, not only the first. No Hub MCP/server, provider host, or Laya inference was launched, per user instruction.

## 2026-11-24 source-only provider acceptance rerun

- Provider bundle plus managed-hook suites — 69 passed, 1 Windows symlink skip. OpenCode adapter — 3 passed; OpenCode plugin — 5 passed; selected active Laya model-route, next-step, retrieval and high-risk fallback cases — 6 passed.
- Canonical `local-ai-orchestrator` skill content is byte-identical in all seven packaged provider snapshots (Antigravity, Claude, Codex, Copilot, Cursor, Devin, Gemini CLI).
- These checks verify offline source contracts only. No Hub/MCP server, provider host, or Laya inference was started; host handshakes and model/device acceptance remain open.

## 2026-11-24 orchestrator skill provider discovery

- A pressure-test using Antigravity setup, OpenCode skill loading, and Devin Local setup prompts found the canonical skill description did not name those supported providers. Updated it to a trigger-only `Use when...` description covering Codex, Antigravity/Gemini CLI, Claude, Cursor, Windsurf, VS Code/Copilot, Devin Local, OpenCode, and other MCP coding agents.
- The new provider-bundle regression failed on the old description, then passed after the canonical skill and seven packaged snapshots were updated. Bundle plus managed-hook rerun: 70 passed, 1 Windows symlink skip; all seven packaged snapshots are byte-identical to canonical. No Hub or provider runtime was used.
- OpenCode setup now has an isolated install regression proving `local-ai-orchestrator/SKILL.md` is copied to the documented global `~/.config/opencode/skills` discovery root. All OpenCode setup selections passed — 11 passed; no Hub MCP or OpenCode host was launched.
