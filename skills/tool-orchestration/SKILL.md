---
name: tool-orchestration
description: Use for multi-step engineering work across repositories.
---

# Tool Orchestration

Use this sequence for engineering tasks: discover, inspect, reason, act, verify, review.

## Discover and inspect

On first work in each stable repository root, resolve the absolute Git root and inspect `.local-ai.toml` plus any applicable `.local-ai.worktree.toml`. If settings are missing or incomplete, add only evidence-backed exclusions, uncommon text/binary extensions, pinned docs, and entry points; preserve existing values and use Hub defaults when sufficient. Then call `local_ai_repo(action="preprocess", root=ABS_ROOT)` once for idempotent registration. Do not force-refresh or poll asynchronous preprocessing.

Reuse fresh repository evidence before adaptive retrieval or native broad discovery.

- Start with `local_ai_repo` for bounded repository evidence. Supported actions: `search`, `code_index`, `context`, `solve`, `review_diff`, `callers`, `dead_code`, and `preprocess` for registration.
- Use exact artifact slices for source details. Use adaptive context only when indexed evidence is insufficient.
- Check the active MCP schema before relying on any tool or action.

## Reason and act

- Define scope and acceptance criteria. For substantial work, create a task contract and query relevant memory with supported `local_ai_coord` actions.
- Make localized edits and preserve unrelated user changes.
- Use `local_ai_task` for bounded semantic reasoning, review or second opinion when an approved backend is available. Deterministic/indexed evidence remains authoritative for exact facts and diffs.

## Verify and review

- Run bounded project checks with the host-native command tool; the Hub has no command-runner tool.
- Use `local_ai_repo(action="review_diff")` when relevant, then inspect the diff and validation output.
- Do not claim completion without evidence. Do not commit, push or publish unless the user explicitly asks.


## Context economy contract

- Every Hub response is aggregate-bounded (default ≈3200 tokens).
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`; for Hub-unknown commands, require `native_fallback_allowed=true` plus native-tool authorization.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls report `unchanged=true`. Required task memory may remain inline.
- Use the existing `local_ai_task(action="batch")` for independent local tasks; keep each item bounded and consume compact per-item results.
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or the Hub command/repository tools for discovery.
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned.
- Reuse fresh sufficient repository evidence; use bounded indexed/source lookup directly before native broad discovery.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure.
