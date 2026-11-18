---
name: tool-orchestration
description: Use for multi-step engineering work across repositories.
---

# Tool Orchestration

Sequence: discover -> inspect -> reason -> act -> verify -> review.

## Discover and inspect

First work in stable root: resolve absolute Git root, inspect `.local-ai.toml` and `.local-ai.worktree.toml`. Add only evidence-backed exclusions, uncommon extensions, pinned docs, entry points. Register once: `local_ai_repo(action="preprocess", root=ABS_ROOT)`. Never force-refresh or poll preprocessing.

Reuse fresh repository evidence before adaptive retrieval or native broad discovery.

- `local_ai_repo`: bounded evidence (`search`, `code_index`, `context`, `solve`, `review_diff`, `callers`, `dead_code`, `preprocess`).
- Source details: exact artifact slices. Adaptive context only when indexed evidence insufficient.
- Check active MCP schema before calling tools.
- If the schema has no action for a requested operation, skip Hub and use the authorized native tool directly (for example, `git worktree list`); no Hub error is needed. Apply terminal/retryable fallback gates only after calling an advertised Hub action.

## Reason and act

- Define scope and criteria. Substantial work: task contract + scoped memory via `local_ai_coord`.
- Localized edits; preserve unrelated user changes.
- `local_ai_task`: bounded semantic reasoning, review, second opinion after evidence. Deterministic/indexed evidence authoritative.

## Verify and review

- Host-native command tool for bounded checks.
- `local_ai_repo(action="review_diff")`: inspect diff and validation output.
- No completion claim without evidence. Never commit/push without explicit user request.

## Context economy contract

- Every Hub response is aggregate-bounded (default ≈3200 tokens).
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- For a response-budget rejection, reduce the requested envelope or fetch a smaller artifact page/slice; do not replay the same oversized request.
- For large plans, query `plan_board_view` with the exact `task_id`, use the card's `plan_file_revision`, and fetch exact plan-file slices only when needed; avoid full-plan responses.
- If the live MCP schema has no action for an operation, skip Hub and use the authorized native tool directly; no Hub failure or `native_fallback_allowed` signal is needed. After calling an advertised Hub action, native fallback requires explicit `terminal=true` and `retryable=false`.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
- Prefer `response_profile="minimal"`/`"compact"`; request only decision-grade fields.
- Pass a stable `reuse_key` for repeated logical queries. Use `response_profile="delta"` when only changes are needed; unchanged calls report `unchanged=true`. Required task memory may remain inline.
- Use the existing `local_ai_task(action="batch")` for independent local tasks; keep each item bounded and consume compact per-item results.
- The Hub keeps a bounded metadata-only context ledger; inspect it only with an explicit cache/status request, never by replaying the whole session.
- Broad native shell reads are guarded by the optional host hook; use bounded limits or Hub repository tools for discovery.
- Commands return status, summary, changed paths, and failures; full stdout/stderr is retrievable only when `output_artifact_id` is returned.
- Reuse fresh sufficient repository evidence; use bounded indexed/source lookup directly before native broad discovery.
- Do not bypass the budget with native broad reads unless Hub has one bounded terminal failure.
