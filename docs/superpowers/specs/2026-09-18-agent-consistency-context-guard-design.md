# Agent Consistency Guard and Adaptive Context Pack Design

## Goal

Make default agent execution more consistent across backend and frontend work while reducing duplicate discovery, scope drift, invented code facts, and unnecessary new abstractions. Every agent receives a bounded, task-specific context pack assembled from deterministic repository evidence, project preload rules, durable memory, local semantic ranking, and a provenance-preserving local-model post-process.

## Design principles

- Default-on for every agent and task; no opt-in profile required.
- Evidence before inference. Local models may rank, identify gaps, and compress verified evidence, but may not invent repository facts.
- Reuse before creation. Existing symbols, components, endpoints, schemas, services, tests, and patterns are surfaced before new public abstractions are proposed.
- Soft enforcement. Drift and novelty produce actionable warnings and an explicit override path, not a hard block.
- Bounded context. Agents receive only relevant, token-budgeted slices and a delta when an earlier pack remains valid.
- Provenance and freshness. Every claim has evidence IDs, a repository revision, confidence, and stale/conflict state.
- Compact public MCP surface. Add the capability behind existing repository/context and coordination tools unless a separate schema materially reduces usage cost.
- Durable memory stays safe. Store concise metadata-backed facts, not prompts, full source, secrets, or unconstrained model prose.

## User-facing capability

Extend the existing `local_ai_repo` MCP tool with a bounded `action="context"` operation. It accepts a repository root, task ID or task contract, execution phase, focus terms, optional preload profile, and token budget. It returns a `context_id` plus a structured context pack and artifact-backed detailed slices.

Example request:

```json
{
  "action": "context",
  "root": "C:/repo",
  "task_id": "task-123",
  "phase": "edit",
  "focus": ["user profile", "BE endpoint", "FE form"],
  "budget": 6000,
  "response_profile": "compact"
}
```

Stable response fields:

- `context_id`, `repo_revision`, `stale`, and `warnings`;
- `contract` with goal, non-goals, acceptance criteria, scope, risk, and change budget;
- `relevant_files`, `symbols`, `callers`, and exact `evidence_ids`;
- `reusable_candidates` with source locations and reuse decisions;
- `be_fe_contract` mappings and mismatches;
- `memory_findings`, `negative_knowledge`, `decisions`, and `unknowns`;
- `next_actions`, affected tests, and validation commands.

The response is bounded. Large source slices, plans, diffs, and model explanations remain artifact-backed and are fetched lazily.

## Context-pack pipeline

1. Normalize the task into the existing Agent OS task contract. Preserve user wording, derive non-goals and acceptance criteria only when unambiguous, and mark unresolved interpretation as `unknown`.
2. Read the current repository fingerprint, branch/revision, changed paths, leases, and task checkpoints.
3. Load configured project preloads, agent instructions, architecture documents, relevant memory, negative knowledge, prior similar task findings, and known conventions.
4. Run deterministic/indexed discovery first: changed paths, code index, symbols, callers, imports, schemas, tests, route/component/service candidates, and exact bounded evidence slices.
5. Run reuse-first analysis. Rank existing candidates for every requested new endpoint, component, hook, service, DTO/schema, validation, error pattern, or test fixture. Record the reason when a candidate is rejected.
6. Build BE/FE contract mappings from evidence. Detect missing client types, response mismatches, error handling gaps, and loading/empty/error-state omissions.
7. Run a local model relevance pass over structured evidence only. It may select evidence, identify conflicts or gaps, and propose bounded follow-up queries. It may not assert unsupported code facts.
8. Fetch only approved follow-up evidence, then run a local model composition pass. Compose phase-specific context with explicit citations, confidence, unknowns, reuse recommendations, and a short checklist.
9. Post-process and validate the model output. Drop unsupported claims, attach evidence IDs, mark stale/conflicting facts, enforce token limits, redact sensitive fields, and emit actionable warnings.
10. Persist only new compact findings and decisions. Cache the pack by repository revision, contract fingerprint, phase, focus, preload profile, and memory revision.

## Phase-specific packs

### `plan`

Task contract, non-goals, relevant architecture, reusable candidates, known constraints, risks, unknowns, proposed bounded steps, and acceptance mapping.

### `edit`

Exact files and symbols, relevant code slices, existing patterns, BE/FE mappings, allowed scope, reuse decisions, active leases, and edit checklist.

### `review`

Current contract, diff, changed paths, scope deviations, reuse violations, BE/FE mismatches, invented-symbol findings, stale evidence, and missing tests.

### `test`

Affected tests, expected behavior, fixtures, validation commands, prior failures, and criteria-to-test mapping.

### `handoff`

Changed paths, verified findings, decisions, rejected approaches, unresolved unknowns, stale records, validation receipts, and next actions.

## Consistency guard

The guard runs at task creation, before plan execution, before edits, after meaningful checkpoints, before validation, and before completion. It compares:

```text
task contract vs. plan
plan vs. changed paths
diff vs. acceptance criteria
BE contract vs. FE contract
new abstraction vs. reuse candidates
claims vs. evidence
current revision vs. context-pack revision
```

Checks are soft by default and use three escalation levels. Informational findings do not interrupt execution. Ordinary warnings include the finding, evidence, affected paths, likely impact, and recommended next action; the agent may continue by supplying a concise reason. Boundary or high-risk findings move the task to a waiting/approval state until the user or an authorized coordinator approves the exception; this remains recoverable and is not a destructive hard rejection. Every justification or approval becomes a durable `decision` linked to the task and current revision. Repeated warnings are escalated visually and in the completion audit.

## Reuse-first rules

Before a new public symbol or cross-layer contract is accepted, the guard requires a reuse search over indexed repository evidence. Candidates include:

- backend endpoints, services, repositories, DTOs, schemas, error codes, validators, and fixtures;
- frontend clients, types, hooks, components, state machines, loading/empty/error states, and test helpers;
- project conventions and existing architecture patterns.

The result records `reuse_candidate`, `reuse_decision`, or `no_candidate`. New code is allowed when no suitable candidate exists or the agent records why reuse would violate the contract, behavior, ownership, or dependency boundary.

## Evidence memory

Use the existing memory API and extend its record payload rather than adding a parallel store. Automatic records are created at discovery, reuse decisions, important decisions, failed approaches, validation, soft-stop overrides, and completion.

Supported memory kinds:

- `finding` — verified repository fact;
- `reusable_candidate` — existing implementation suitable for reuse;
- `contract_mapping` — BE/FE relationship;
- `decision` — accepted scope or design decision;
- `rejected_approach` — failed or intentionally rejected path;
- `assumption` — explicit assumption awaiting confirmation;
- `unknown` — unresolved question that must not be guessed;
- `validation` — test, lint, typecheck, build, or receipt result.

Required provenance metadata:

- `kind`, `scope`, `key`, and compact `value`;
- `evidence_ids` and optional path/symbol references;
- `confidence`, `status`, and repository revision;
- task/branch relation and optional supersession relation;
- timestamps and bounded retention metadata.

Default scope is repository. Task and branch facts are more volatile. Promotion to project, user, or global scope requires explicit approval. Repository revision changes mark affected findings stale; conflicts remain visible rather than being silently merged. Context compilation retrieves only relevant, fresh records and can include a bounded stale/conflict summary.

## Preload profiles

Projects may configure bounded preload files, patterns, and memory kinds. Defaults include agent instructions, README/architecture material, current task contract, relevant changed paths, checkpoints, negative knowledge, and previous similar findings. Preloads are indexed and fingerprinted, not copied into every response.

## Hallucination controls

- Require symbol/file/import/schema existence checks before citing them as facts.
- Mark unsupported model claims as `unknown` and exclude them from authoritative context.
- Attach evidence IDs to every composed claim.
- Preserve source revision and stale state.
- Surface conflicting evidence explicitly.
- Prefer exact slices over free-form summaries for edits and APIs.
- Keep model-generated suggestions separate from verified findings.
- Never persist raw prompts, full source, secrets, or unconstrained model output in memory or telemetry.

## Completion audit

The existing verification flow gains a consistency section:

- every acceptance criterion mapped to evidence and validation;
- no unexplained scope drift;
- all reuse candidates accepted or rejected with reasons;
- BE/FE contract matrix has no unresolved required mismatch;
- invented-symbol and stale-evidence findings are resolved or explicitly accepted;
- validation receipts reference the current revision.

The final result is a compact traceability report:

```text
requirement -> change -> evidence -> validation -> result
```

## Caching, invalidation, and failure behavior

- Cache keys include repository revision, task-contract fingerprint, phase, focus, preload profile, and memory revision.
- Same-scope requests reuse the pack; changed files return a delta pack where possible.
- Revision changes invalidate only affected evidence and mappings.
- Local-model failure falls back to deterministic/indexed context with an explicit degraded warning.
- Optional code-intelligence backend failure falls back to built-in indexes.
- Context assembly stays bounded; subprocesses and model waits use existing hard timeouts.
- No guard failure may make ordinary repository inspection unusable.

## Compatibility and rollout

- Existing task, memory, context, lease, and verification actions remain compatible.
- Existing callers continue receiving their current fields.
- Guard metadata and warnings are additive.
- Default behavior is enabled for all agents.
- Existing explicit bypasses remain available, are recorded, and appear in adoption telemetry.
- No migration shim or deprecated alias is introduced.

## Testing

- Contract normalization preserves explicit user scope and derives non-goals only when safe.
- Context packs are phase-specific, bounded, cacheable, and revision-aware.
- Deterministic evidence precedes local-model composition.
- Unsupported model claims are dropped or marked `unknown`.
- Memory records require provenance, become stale after relevant revision changes, and preserve conflicts.
- Reuse checks surface candidates and require reasons for rejection.
- BE/FE mapping detects response/type/error/loading-state mismatches.
- Soft-stop warnings allow justified continuation and persist decisions.
- Drift checks detect plan/diff/scope divergence.
- Existing public MCP payloads remain backward compatible.
- Fallback behavior works when optional indexes or local models are unavailable.
- Release, compile, unit, and self-test gates cover the new default path.

## Out of scope

- Autonomous code edits without agent confirmation.
- Hard policy enforcement that makes every warning blocking.
- Global memory learning without explicit promotion.
- Replacing the existing repository index, Agent OS, leases, or verification system.
- Persisting raw prompts, source dumps, secrets, or model transcripts.
