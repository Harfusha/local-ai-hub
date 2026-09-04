# Agent Adoption Nudges Design

**Date:** 2026-09-03
**Status:** Design approved; specification pending user review

## Goal

Increase voluntary use of Local AI Hub features by making the right tool and action obvious at the moment an agent begins a task. Do not block native tools, force a fixed workflow, add a new MCP tool, or require every feature on every task.

## Root cause

The current setup installs the MCP server and routing policy, but the policy is dense and mostly descriptive. It lists capabilities without enough task-trigger language or short examples. Agents therefore discover the server yet still default to shell search, direct reasoning, or AGY delegation.

## Design

### 1. Front-loaded routing card

Update the shared policy source in `tools/setup.py` so the first lines contain a compact trigger map:

- repository facts, files, symbols: `local_ai_repo`
- tests, lint, typecheck, build, safe repeatable commands: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- bounded local generation or second opinion: `local_ai_task`

Keep the existing cheapest-first and fallback rules below this card. Preserve policy markers and managed-block merging so unrelated user instructions remain unchanged.

### 2. Lifecycle recipes

Add three short recipes to the shared policy and skill:

1. **Explore:** preprocess once, use the cheapest repository action, fetch only required evidence slices.
2. **Change:** gather indexed evidence, use `solve` before edits, claim coordination leases when paths overlap, then run indexed impact/review before validation.
3. **Validate:** route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.

Recipes are guidance, not gates. They must state when a step is unnecessary or when one bounded fallback is allowed.

### 3. MCP tool discoverability

Update docstrings/descriptions for the seven top-level tools with a one-line `Use when` cue and one-line `Skip when` cue. Keep the compact seven-tool surface and existing action enums. Action names remain source of truth; descriptions only improve selection.

### 4. Generated and installed artifacts

Continue sourcing generated policy from the single `GLOBAL_POLICY` constant. Ensure generated generic and VS Code manifests still expose the same Local AI server and agent profile environment. No direct Serena or CodeGraph MCP entries become default.

### 5. Adoption evidence

Add tests that assert:

- every Hub feature family appears in the trigger card;
- lifecycle recipes mention the relevant actions;
- all seven MCP tools have discoverability cues;
- generated policy remains identical to the shared policy;
- unrelated host configuration remains preserved.

Do not add telemetry, automatic retries, or runtime rejection in this change. Adoption measurement can be a separate follow-up if needed.

## Acceptance criteria

- Installed policy starts with actionable task-to-tool mapping.
- Agents can select each feature family from a concrete task cue.
- Existing users retain unrelated configuration and current MCP compatibility.
- No workflow becomes mandatory and no feature is invoked merely for coverage.
- Focused setup/MCP tests pass, then full project validation passes.

## Scope

In scope: shared policy, orchestrator skill, MCP descriptions, generated artifacts, focused tests.

Out of scope: new MCP tools, runtime enforcement, model routing changes, telemetry dashboards, host-specific vendor integrations.
