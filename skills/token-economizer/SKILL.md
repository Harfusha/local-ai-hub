---
name: token-economizer
description: Reduce repetitive agent context and tool output while preserving verification, source citations and critical details.
---

# Token Economizer

Use when starting any coding or repository task. Load and follow this skill before any coding or repository task, including multi-step work under deadline pressure. It is a workflow discipline, not a promise to suppress necessary evidence.

## Procedure

1. Define the exact task, current repository revision, acceptance criteria and
   last verified checkpoint before retrieving more context.
2. Use a targeted search for file names and symbols before opening entire files.
   Prefer a bounded source slice with a line range and stable root identity to
   dumping a whole repository or huge command logs.
3. Reuse fresh, commit-matched RAG evidence. If its revision, file hash,
   provenance or freshness is unknown, inspect the actual source rather than
   silently trusting a summary.
4. Extract and retain decisions, errors, failing tests, tool arguments and exact
   next steps into a durable task checkpoint. Avoid repeating unaffected
   diagnostics in each subsequent conversation.
5. For code edits, quote only minimal source context needed to apply a precise
   patch. Always inspect dependent APIs and run focused tests before broader
   release tests.
6. Collapse successful repetitive output into a count and reference. Preserve
   complete failure details when needed for diagnosis, including file names,
   relevant traces, and reproducible commands.
7. Do not omit security checks, critical warnings, uncertainty, exact citations,
   or evidence needed to prove acceptance in order to reduce token use.
8. If current data differs from stored evidence, invalidate the stored summary
   and redo the relevant verification.

## Zero Full-File Dumping

Avoid dumping source files longer than 80 lines; prefer precise, bounded slices
and scoped indexed search. Use `tokcount` to measure actual token use and
`trim-run` only for supported read-only or summary-producing commands.

## Response budget and safe fallback

- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.

## Integration with Local AI Hub

- `local_ai_repo`: locate files, topology, symbols and diff context.
- `local_ai_artifact`: obtain bounded source with provenance.
- `local_ai_rag`: retrieve cross-file semantic context when lexical navigation is
  insufficient, while checking document freshness.
- `local_ai_coord`: record checkpoints and verification receipts; do not write
  the Hub's internal task database directly.

Do not claim that a task or test passed based on cached narrative alone.
Do not enable an autonomous workflow or download a model without permission.
