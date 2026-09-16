# Agent Efficiency and Observability Design

## Goal

Make Local AI Hub prove token/cache behavior, return compact navigable repository evidence, safely diagnose command failures, and reduce avoidable status polling without changing trusted command-policy defaults.

## Constraints

- Public MCP action schemas remain stable `Literal` sets. New capabilities use canonical action names only.
- Command-policy blocking remains disabled by default. Existing unconditional dangerous-command denial remains unchanged.
- Telemetry stores only numeric usage, tool/action identifiers, cache status, and opaque task identifiers. It never stores prompts, source, response text, paths, timestamps, or provider request IDs.
- Batch replacement remains atomic, requires one unique expected match per edit, never commits, and refuses targets overlapping unowned dirty hunks.
- Speculative lint is opt-in, read-only, debounced, cancellable, and restricted to changed files.

## Telemetry and Generation Cache

Add measured `input_tokens`, `cache_read_tokens`, and `output_tokens` to provider result normalization. Record them in existing telemetry with tool/action and opaque task/work identifiers. Preserve provider timestamps and request identifiers in provider-local diagnostic responses; do not normalize them for cache keys.

Generation cache keys use exact prompt/system content after line-ending normalization only. Dashboard and telemetry aggregate measured token fields by tool/action, cache state, and task kind. No cache-hit or savings claim is emitted when provider usage is unavailable.

## Repository Navigation

`local_ai_repo(action="search", include_code=true)` returns each hit with bounded surrounding lines, the smallest enclosing symbol when known, and a verifiable evidence identifier. `ast_outline` remains the separate structural navigation endpoint. Results retain current compact projection unless callers explicitly request source fields.

## Batch Replacement

`local_ai_repo(action="batch_replace")` accepts only a non-empty explicit `edits` array. Each edit names a project-relative file, exact old text, and replacement text. All replacements validate before writes; any missing, ambiguous, syntax-invalid, root-escaping, or unowned dirty-hunk edit aborts all writes. Python syntax preflight uses in-memory `compile()` and writes no bytecode. `staged=true` remains dry-run compatibility behavior until a dedicated `dry_run` argument can be introduced without schema churn.

## Command Failure Distillation

Command execution first extracts failing test, path, line, and error deterministically. Full bounded stdout/stderr is stored as an artifact. When deterministic extraction cannot identify a failure location, submit only the failure excerpt and artifact identifier to `local_ai_task`; never submit full logs or source. The returned response contains concise distillation plus artifact reference.

## Speculative Lint

Introduce a disabled-by-default configuration block. An explicit opt-in request queues a read-only lint job after a debounce interval. A newer request for the same root cancels the older queued job. Only caller-supplied changed paths are eligible; no formatter, auto-fix, command cache, or single-flight mutation path is used.

## Polling Reduction

Expose task-contract guidance and durable-job completion data through existing `local_ai_coord` and `local_ai_task` actions. Record wait count and wait duration as numeric telemetry. Generated install/update prompts instruct agents to create one contract, checkpoint phase changes, use one bounded wait, and avoid status loops. Hub cannot alter Codex desktop `wait_agent` behavior directly.

## Validation

Add deterministic unit tests for each contract above, including unavailable provider usage, cache-key preservation, enriched search fields, dirty-hunk batch rejection, bytecode-free syntax preflight, distiller fallback/artifact behavior, lint debounce/cancellation, and single bounded wait guidance. Run focused suites, full `pytest`, release check, compileall, and selftest.
