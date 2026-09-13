# Telemetry, Reliability, and Cache Correctness

## Goal

Make dashboard telemetry reflect real behavior: deterministic/RG work is not reported as proven cloud savings, operational failures exclude compatibility noise, slow command failures are diagnosable, and reusable local work produces visible cache hits.

## Design

1. **Token accounting**

   Keep measured local context reduction separate from proven cloud-token avoidance. A full `git diff` size is only a counterfactual candidate; it must not become savings merely because the response contains `original_diff_tokens`. Count only explicitly measured delegated context or response projection, bounded by the context actually exposed to the agent. Preserve signed protocol cost and existing privacy guarantees.

2. **Cache telemetry**

   Rename the existing headline to generation-cache hit rate, then expose separate exact counters for generation, repo-result/deterministic, command, semantic, and single-flight reuse. Do not aggregate unlike cache layers into one misleading percentage. Keep cache keys workspace/version/model/context scoped for correctness; improve reuse by excluding presentation-only metadata from keys and retaining stable normalized task/context inputs.

3. **Failure taxonomy**

   Classify unsupported/legacy versioned-endpoint probes as compatibility events, not operational failures. Keep HTTP status and endpoint failures visible in a separate protocol/compatibility section. Preserve real `/api/command` failures, including non-zero exits, timeouts, and policy blocks, with distinct categories.

4. **Latency and validation**

   Bound expensive command/search paths, surface timeout causes, and avoid retrying known terminal failures. Add regression tests first for accounting, cache counters/keys, compatibility classification, and command failure categories. Run focused tests, then the repository validation suite.

## Scope

Modify only telemetry/accounting, cache metric projection/key normalization, HTTP outcome classification, command diagnostics, dashboard labels, and their focused tests/docs. Do not change security policy, tool surface, or delete existing user changes.

## Acceptance criteria

- A large truncated diff cannot create tens of millions of claimed savings without an explicit agent-visible baseline.
- Dashboard distinguishes generation-cache hits from repository/deterministic cache hits and single-flight reuse.
- Legacy versioned-endpoint 404 probes do not inflate operational failure rate.
- Command policy blocks, timeouts, and non-zero exits remain separately countable.
- Repeated identical non-conversational local generation can hit exact/semantic cache; conversations remain uncached unless explicitly made safe.
- Focused regression tests fail before each production change and pass afterward.
