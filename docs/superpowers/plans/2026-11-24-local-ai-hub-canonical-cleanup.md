# Local AI Hub Canonical Cleanup Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to complete tasks one at a time. Keep ownership in the primary agent and preserve all current user work.

**Goal:** Remove obsolete runtime compatibility and repository ballast while keeping supported upgrades safe through explicit migrations and deriving public MCP, provider, skill, instruction, and documentation surfaces from canonical contracts.

**Architecture:** First classify current runtime and stored-format contracts. Define migration-only ownership for old formats. Remove compatibility paths only after migration coverage and current callers are proven. Make generators and docs consume the same current contract, then remove proven dead material and validate the integrated tree.

**Tech Stack:** Python 3.11+, TOML/JSON, MCP/HTTP contracts, Hub project plans, provider plugin packages, pytest and repository release tooling.

**Spec:** `docs/superpowers/specs/2026-11-24-local-ai-hub-canonical-cleanup-design.md`

## Global Constraints

- No runtime aliases, dual-read/dual-write, deprecated endpoints, or compatibility fallbacks retained solely for old clients or formats.
- Versioned update migrations are the only code allowed to interpret retired persisted formats.
- Migrations preserve authoritative data, use recoverable backups and atomic boundaries where supported, validate output, and fail closed on ambiguous conversion.
- Preserve authorization, single-owner scope, task/session identity, privacy, path confinement, quality gates, writer leases, and authentic receipts.
- Preserve and classify every existing dirty or untracked change; no blanket cleanup, reset, stash, or deletion.
- Remove historical artifacts only after proving they are not required by supported migration, current tests, or linked evidence.
- Keep static checks, isolated migration tests, historical fixtures, live runtime, and cross-provider acceptance distinct.

## Review Focus

- Ambiguous old state must stop migration before runtime opens it; cover refusal and backup recovery in migration tests.
- Retired aliases must be rejected at every public boundary, not normalized by SDK, HTTP, MCP, config, or provider adapters.
- Profile-disabled tools must stay absent from schemas, installed manifests, skills, and instructions.
- Provider-specific package layouts must remain correct while shared contract text is generated once.
- Historical fixtures may contain legacy names intentionally; prove they are migration/test inputs before calling them runtime support or deleting them.

## File Map

- `src/local_ai_hub/operation_contracts.py`, `generator.py`, `mcp_*.py`, `client.py`: current public action, schema, and adapter boundaries.
- `src/local_ai_hub/config.py`, `config_flattening.py`, `project_config.py`, `migration_*.py`, and state-store migration modules: current configuration and persisted-state migration boundary.
- `tools/update_install.py`, `tools/update_transaction.py`, `tools/setup.py`, `tools/sync_prompt_policies.py`: update ordering and generated installation artifacts.
- `plugins/*/local-ai-hub/**`: provider-specific generated/package surfaces; inspect the complete supported provider matrix before editing.
- `docs/*.md`, `docs/superpowers/**`, `docs/agent-evaluation/**`: current operator guidance, approved design/plan, and historical evidence.
- `tests/test_*migration*`, `test_operation_contracts.py`, `test_mcp_wire_contract.py`, `test_generator.py`, `test_feature_surface_parity.py`, setup and provider integration tests: focused acceptance for the owning tasks.

---

### Task 1: Inventory and classify existing work

**Files:** Read-only inventory of current source, generated surfaces, docs, tests, active Hub plans, Git diff, and untracked files.

**Produces:** A reviewable inventory linked from the Hub task: contract owner, observed caller, old-format handling, evidence for removal/retention, and overlapping dirty paths. No source deletion in this task.

- [ ] Inspect active plans and current diff; map each dirty path to its current owner and planned integration.
- [ ] Enumerate config/API/HTTP/MCP/SDK aliases, compatibility routes, dual-read/write storage, fallback branches, and migration versions.
- [ ] Compare generator inputs and outputs for every supported profile/provider; identify duplicated manually maintained text and stale manifests.
- [ ] Audit dependency declarations, imports, script entrypoints, packaged files, docs, fixtures, and generated artifacts for referential reachability.
- [ ] Classify each finding as current product behavior, migration-only support, supported test oracle/history, confirmed obsolete, or unresolved.
- [ ] Record unresolved items as blocked with evidence needed; do not infer removability from keyword matches.

**Verification:** Hub plan/task records and a source-linked inventory. No test execution or file mutation in this task.

### Task 2: Establish migration-only compatibility boundary

**Files:** Exact migration and updater files discovered in Task 1; `tests/test_agent_state_migrations.py`, `tests/test_agent_state_migrations_root.py`, `tests/test_agent_t08_migration_recovery.py`, plus exact focused tests found in Task 1.

**Interfaces:** Update invokes ordered migrations before runtime open; migration inputs identify source schema/version; output is current schema/version or an actionable terminal error.

- [ ] Add focused migration coverage for each supported retired persisted format and each ambiguous/unconvertible case.
- [ ] Run those tests to confirm old formats are read only by migration and failures preserve recoverable source state.
- [ ] Implement ordered version detection and migration dispatch in the updater; write backup/atomicity and verification record before declaring success.
- [ ] Remove runtime old-format reads/writes only after their migration path and rollback behavior pass.
- [ ] Run the focused migration and update-transaction tests; retain exact command/result and revision in the Hub plan.

### Task 3: Remove runtime compatibility aliases and duplicate contracts

**Files:** Task 1 findings in `src/local_ai_hub/config.py`, `client.py`, HTTP route modules, MCP adapters, `operation_contracts.py`, store readers/writers, and corresponding tests.

**Interfaces:** Each runtime boundary accepts one canonical current schema and rejects retired names with stable actionable errors. Domain fallback behavior remains when it is a present-day product requirement.

- [ ] For each alias or compatibility route, add a focused rejection test at its public boundary and retain a positive canonical-path test.
- [ ] Run each targeted test to prove the current contract before implementation changes.
- [ ] Remove normalization aliases, duplicate public paths, deprecated wrappers, and silent format fallback in dependency order; keep conversion code only in explicit migrations.
- [ ] Update SDK/client/provider adapters so they send only canonical fields and surface version/shape errors without retrying an old contract.
- [ ] Run affected operation, HTTP, MCP wire, and state-store tests; audit remaining compatibility hits against the inventory.

### Task 4: Unify MCP, provider, skill, and instruction generation

**Files:** `src/local_ai_hub/generator.py`, `operation_contracts.py`, `mcp_tool_descriptions.py`, `tools/setup.py`, `tools/sync_prompt_policies.py`, shared skill sources, provider plugin bundles, and `tests/test_generator.py`, `tests/test_generator_action_descriptions.py`, `tests/test_feature_surface_parity.py`, `tests/test_prompt_contracts.py`, `tests/test_provider_plugin_bundles.py`.

**Interfaces:** A single active contract/capability model supplies action names, argument schemas, descriptions, triggers, and profile gates. Provider adapters add only host-specific packaging; generated output cannot reintroduce a retired alias.

- [ ] Add contract-parity checks for all supported providers and profiles, including disabled actions and retired aliases.
- [ ] Consolidate shared action/capability text at the canonical owner; retain only necessary provider-specific layout adapters.
- [ ] Generate or package MCP schema, agent skill, instructions, and API coverage from the same active definitions.
- [ ] Regenerate all tracked outputs through supported tooling and inspect exact diffs before accepting them.
- [ ] Run focused generator, setup, provider-bundle, and capability-parity tests.

### Task 5: Reconcile documentation and historical evidence

**Files:** `docs/HTTP_API.md`, `docs/PYTHON_SDK.md`, `docs/CONFIGURATION.md`, migration/update/install guidance, generated instructions, provider matrix, and linked evaluation/handoff artifacts identified in Task 1.

- [ ] Trace every current-contract statement to a generated source, implementation, or verified runtime observation.
- [ ] Replace outdated compatibility instructions with migration-only upgrade behavior and explicit rejection behavior.
- [ ] Label retained historical audit/evaluation records as historical and preserve their provenance; remove only records proven unreferenced and nonessential.
- [ ] Run doc/API surface consistency checks and review the rendered or packaged instruction output for all supported providers.

### Task 6: Remove proven repository ballast

**Files:** Only dead modules, duplicate generators, unused dependencies, superseded docs/fixtures, and stale generated output proven in Task 1 and approved by a plan task.

- [ ] Add or update a focused reference/dependency manifest check for each proposed removal.
- [ ] Confirm there are no supported import, entrypoint, migration, test-oracle, packaging, or external contract references.
- [ ] Remove one bounded group at a time and inspect the full diff, including untracked files and package manifests.
- [ ] Run focused package/dependency/reachability checks for each group; retain reason and evidence with the task.

### Task 7: Integrated acceptance and completion audit

- [ ] Run `python tools/release_check.py` and `python -m compileall -q src tools tests` on the integrated current revision.
- [ ] Run relevant migration, contract, generator, provider, and critical tests with fresh results; use `pytest --run-all` only if explicitly requested.
- [ ] Run `python tools/selftest.py` and relevant installer/provider roundtrip checks.
- [ ] Verify every current profile/provider output against the canonical contract and confirm retired aliases are rejected.
- [ ] Inspect final `git diff`, plan status, and migration evidence; record live provider/runtime verification separately from static checks.
- [ ] Complete the Hub plan and Codex goal only when every acceptance criterion has authentic current-revision evidence.
