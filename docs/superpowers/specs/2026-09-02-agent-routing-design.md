# Agent Routing Hierarchy Design

**Date:** 2026-09-02

**Status:** Approved by user; implementation pending.

## Goal

Make the main cloud agent the orchestrator, use AGY subagents for small but fuzzy or open-ended delegated work, and make Local AI Hub the default worker for precise, bounded microtasks.

## Routing contract

```text
Main agent: planning, decomposition, architecture, decisions, integration, final ownership.
AGY subagent: delegated work whose boundaries or answer are not yet clear.
Local AI Hub: bounded work with a known input, operation, and output contract.
```

The main agent remains responsible for selecting the tier and validating returned work. No server-side router may silently replace that decision.

## Tier selection

Use AGY when the delegated task needs independent exploration, judgment, architecture discovery, ambiguous scoping, or a result that may redefine the work boundary.

Use Local AI Hub when the task is deterministic or narrowly specified: repository search/indexing, symbol and import lookup, impact analysis, security/dependency checks, test targeting/generation, diff review, evidence retrieval, compression, second opinions, or repeatable validation.

Use `local_ai_task` for bounded local-model work (`review`, `second_opinion`, `compress`, `delegate`, and `batch`). Use `local_ai_rag` only when indexed retrieval cannot answer a genuinely semantic question. Use `local_ai_coord` only for overlapping multi-agent edits or reusable handoffs.

## MCP discoverability changes

Keep the seven top-level MCP tools for compatibility. Improve their descriptions and schemas so the action contract is visible at selection time:

- `local_ai_repo` exposes action groups by lifecycle: discover, understand, change-risk, quality, evidence, and control.
- `local_ai_task` labels each action with its bounded use case and explicitly excludes orchestration.
- `local_ai_rag`, `local_ai_coord`, and `local_ai_artifact` state their triggering conditions and non-use cases.
- `local_ai_command` remains the command broker, but its description no longer implies it is the primary Local AI Hub entry point for every task.

Where the MCP SDK supports it, action parameters use an explicit enum. The server continues to validate unknown actions and returns concise next-action guidance for invalid or misplaced requests.

## Agent policy changes

The reusable orchestrator policy and workflow reference will contain:

1. A tier-selection decision table.
2. A bounded-task checklist before calling Local AI Hub.
3. AGY delegation criteria for fuzzy work.
4. Lifecycle recipes: discovery, pre-edit impact, implementation, post-edit review, validation, and handoff.
5. Explicit prohibition against using AGY for deterministic tasks already covered by Hub tools.
6. Explicit prohibition against using Local AI Hub as the final architectural decision-maker.

The policy will recommend high-impact Hub actions at the moment they become relevant, rather than listing them as optional capabilities only.

## Runtime and telemetry

Existing Hub behavior remains authoritative for caches, timeouts, leases, evidence, and model tiers. This change only improves caller selection and descriptions. Add adoption metadata at the MCP boundary where available: top-level tool, action, agent tier, and workflow phase. Preserve existing privacy rules; do not store prompts, source text, or model output.

Telemetry must distinguish:

- top-level tool usage from action usage,
- bounded Hub work from AGY delegation,
- intended fallback use from accidental underuse,
- status/health overhead from productive work.

## Error handling

Unknown actions fail clearly and list valid actions for that tool. A failed optional backend still follows existing deterministic fallback rules. Hub failure does not trigger automatic AGY delegation unless the main agent explicitly decides that the task has become fuzzy or blocked. AGY failure does not trigger blind Hub retries for an unbounded task.

## Verification

Add tests proving:

- action schemas/descriptions expose the intended action groups and tier boundaries;
- invalid actions return concise guidance;
- policy text contains the tier-selection rules and lifecycle recommendations;
- existing seven-tool names and valid actions remain compatible;
- telemetry projection does not include prompts, source text, or model output.

Run targeted tests first, then the repository validation suite through `local_ai_command`.

## Non-goals

- Do not add a new MCP tool for every action.
- Do not make Local AI Hub autonomously override the main agent's orchestration.
- Do not route every task through AGY.
- Do not force expensive semantic/model calls when deterministic evidence is sufficient.
- Do not change model weights, Ollama residency, or scheduler policy in this change.
