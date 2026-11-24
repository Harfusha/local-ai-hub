# Local AI Hub canonical cleanup design

**Status:** Approved by user on 2026-11-24.

## Goal

Unify Local AI Hub around one current contract, remove obsolete runtime compatibility behavior and repository ballast, and keep upgrades safe through explicit versioned migrations. MCP, skills, instructions, and documentation must describe the same active capabilities and contracts.

## User direction

- Clean up the whole Local AI Hub, including code, MCP/skill/instruction generators, generated surfaces, and documentation.
- Do not retain legacy runtime behavior or backward-compatible aliases and fallbacks.
- Handle previous persisted formats through migrations during update.
- Work in bounded stages against one canonical contract.

## Design

1. **Inventory before removal.** Classify each legacy path, alias, fallback, duplicate generator, stale instruction, unused module, dependency, and historical artifact by actual caller, persistence boundary, and evidence. Treat the current working tree and active plans as owned work; preserve their edits and record overlaps before changing shared files.
2. **One current runtime contract.** Each public API, MCP action, SDK method, configuration value, and persisted current schema has one canonical name and shape. Runtime entrypoints reject retired aliases and incompatible versions with a precise error. Remove compatibility reads, writes, adapters, duplicate routes, and silent fallback behavior when they exist only to support an older contract. Keep domain behavior fallbacks that are current product behavior, not compatibility shims.
3. **Migration is the only old-format reader.** Update runs explicit, ordered, versioned migrations before the new runtime opens state. Each migration has source and destination versions, preserves authoritative data, uses recoverable backup/atomicity appropriate to its store, validates the result, and fails closed with an actionable report when conversion is ambiguous. Runtime modules do not dual-read old and new formats after migration. Retain only migration code and fixtures needed for supported upgrade paths.
4. **Canonical generation.** MCP schemas, provider capability lists, skills, generated instructions, and machine-readable API coverage derive from the current contract and active profile. Eliminate hand-maintained copies where generation is feasible. Generated output must omit disabled actions and retired aliases. Provider-specific packaging remains explicit where host layouts differ.
5. **Documentation follows shipped behavior.** Replace stale compatibility guidance with current contracts and migration instructions. Mark historical evidence as historical; keep it only when it is required by a migration, a maintained test oracle, or an explicitly linked audit record. Do not present unverified, retired, or unsupported behavior as current.
6. **Evidence-based ballast removal.** Remove code, dependencies, fixtures, generated copies, and docs only when source/reference analysis shows they are unused or misleading and no supported update path, security property, test oracle, or audit record depends on them. Avoid broad deletion by keyword.

## Invariants

- Preserve single-owner repository scope, authorization, capability and quality gates, path confinement, privacy, writer leases, task/session identity, and authentic verification receipts.
- Do not change current product behavior merely because a code path contains the word “legacy” or “fallback”; classify semantics first.
- Do not discard user modifications, untracked work, active plans, or authoritative state.
- No automatic model downloads, consent inference, permission expansion, or runtime data rewriting outside the declared update migration.

## Acceptance criteria

1. A reviewed inventory maps every retained compatibility path to a supported migration, historical oracle, security boundary, or current product behavior; all unsupported runtime compatibility paths have an owner task for removal.
2. Supported updates convert old configuration and persisted state before new runtime startup, preserve authoritative records, and report failures without silently opening mixed-format state.
3. Current runtime contracts reject retired aliases and incompatible shapes; no dual-read/dual-write remains outside explicit migration code.
4. MCP schemas, provider packages, generated skills/instructions, and API coverage agree with active capability/action definitions for every supported provider and profile.
5. Current documentation matches generated and observed behavior; historical-only material is clearly labeled and retained only with a traceable purpose.
6. Dead code, duplicate generators, unused dependencies, and unreferenced artifacts are removed only with reference evidence and focused validation.
7. Repository validation and migration/provider checks pass for the final integrated revision; live runtime/provider claims are reported separately from static checks.

## Work decomposition

- Inventory and classify compatibility, generator duplication, document drift, dead code, and dependency residue.
- Establish canonical contract ownership and explicit migration boundary.
- Remove runtime compatibility paths in dependency-ordered slices.
- Consolidate MCP, provider, skill, and instruction generation.
- Reconcile documentation and retire unsupported historic guidance.
- Remove proven ballast, then verify integrated contract, migration, package, and runtime behavior.

## Initial evidence and limits

- The current checkout already has extensive uncommitted work across 128 paths and three active Hub plans. These are not presumed disposable and must be reconciled before overlapping edits.
- Existing source and documentation contain examples requiring audit, including a historical board endpoint, phase/report aliases, old telemetry configuration reads, and a migration guide that still describes a compatibility/degraded runtime path. Search results alone do not establish that each is safe to remove.
- MCP plan tools are not exposed in this session; the repository-supported `tools/hubctl.py plans` / `HubClient` project-plan interface is available and returned the active plan inventory.
