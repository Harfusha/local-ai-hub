# Local AI Hub adoption design

**Status:** approved design
**Date:** 2026-09-17
**Scope:** adoption, routing, observability, and safe use of existing Local AI Hub capabilities. This design does not change source code or runtime configuration.

## Goal

Increase use of the right Local AI Hub capability for each task while preserving safe native fallback and keeping the public MCP surface compact. Success means lower cloud-context volume, fewer unnecessary tool turns, faster diagnosis, and no loss of evidence or validation quality.

## Control plane and routing

The eight existing Hub tools remain the public surface. Do not add a new mega-tool. Do not replace typed action literals with a free-form string.

Use a deterministic intent-to-tool map before native tool use:

| Intent | First choice |
| --- | --- |
| Repository navigation, symbols, impact | `local_ai_repo` |
| Exact source or log excerpt | `local_ai_artifact` |
| Command, test, lint, or build | `local_ai_command` |
| Durable task state, ownership, or checkpoints | `local_ai_coord` |
| Local diagnosis, boilerplate, or second opinion | `local_ai_task` |
| Closed, low-risk delegated work | `local_ai_work` |

Native shell fallback is allowed only after a Hub request returns a terminal, non-retryable failure. Record the task intent, attempted Hub action, failure reason, and fallback path.

Keep `full` schema mode as the default. A future `lean` mode may shorten descriptions only; it must retain every typed action. Provide a stable compact capability map and use an existing route capability for ambiguous intent. Do not create `ultra_lean`, dynamic schemas, or untyped action fallbacks without measured evidence.

Command policy should reduce false positives but retain hard denials, bounded execution, sandboxing, and mutation controls. Cache and single-flight apply only to demonstrably read-only deterministic commands.

## Capability layers

### Repository work

`local_ai_repo(search)` should return the matching text, a small context window, the enclosing symbol where available, and an evidence identifier. `ast_outline` should provide class/function skeletons, signatures, and line locations. `context` and `impact` should remain bounded to relevant files and symbols.

Use `batch_replace` for independent, small edits. It must use exact expected match counts, provide dry-run and rollback behaviour, stop on ambiguity, and never auto-commit or overwrite unrelated dirty hunks.

### Commands and artifacts

Classify commands as read-only, mutating, test/build, or unknown. Read-only commands may use caching, deduplication, and compact output. Mutating commands must not use cache or single-flight and require explicit scope, bounded execution, and a precise result or diff.

Test and build failures should return a deterministic failure summary while retaining complete stdout/stderr as one artifact. The cloud model receives the summary, artifact identifier, and a narrow follow-up slice. Syntax or type preflight must avoid writing generated files and must not replace relevant tests.

### Local inference

Run deterministic parsers before local models. Use `local_ai_task` for ambiguous tracebacks, bounded classifications, fixtures, regular expressions, type annotations, and second opinions. Return structured results with confidence and evidence references. Low-confidence results must expose the relevant raw slice instead of asserting a diagnosis.

### Durable work

Use `local_ai_coord` for task contracts, ownership leases, checkpoints, validation receipts, and completion. Use `local_ai_work` only for closed, low-risk work with explicit acceptance criteria. Do not use either mechanism for micro-edits or live multi-agent discussion.

## Capability health and telemetry

Track every action as `used`, `bypassed`, `blocked`, `failed`, or `dormant`. A capability becomes dormant after 30 days without successful use. First improve its route guidance and capability-map visibility; do not remove or duplicate it without evidence.

Collect per task and intent:

- selected tool/action and native fallback reason;
- provider input, cache-read, and output tokens;
- tool-output and artifact-slice sizes;
- wall-clock time, turns, and native command count;
- first-pass validation, rollback, and repeated-failure rates.

Never store prompts, source content, secrets, or full project paths in telemetry.

## Rollout and gates

1. Capture a 14-day read-only baseline.
2. Release routing prompts, capability map, dashboard views, and fallback telemetry without new capabilities.
3. Enable enriched search, artifact-backed logs, batch replacement, and L1 error distillation behind feature flags.
4. Pilot on 10–20% of suitable tasks and compare with the baseline.
5. Make a capability the default only if tokens, time, and quality gates improve.
6. Consider speculative lint only last; require opt-in, debounce, cancellation, and changed-file scope.

Every new capability must have a single configuration rollback flag. Promotion requires no increase in terminal Hub failures or native fallback rate, no cache/deduplication for mutating commands, no drop in first-pass validation, and preserved raw evidence.

## Expected measurement outcomes

The initial target is a 15–35% reduction in cloud input tokens and 15–40% faster ordinary repository tasks. These are hypotheses, not commitments. Evaluate them per workload category rather than applying one aggregate percentage to all tasks.
