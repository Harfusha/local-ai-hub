# T09 owner provenance / receipt visibility — root-current handoff

- Root: $r, HEAD $(git -C C:\Users\Adam\.local-ai-hub rev-parse HEAD).
- Candidate: $w, detached HEAD $(git -C C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub rev-parse HEAD).
- Patch: $(Split-Path C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub\handoff\t09-receipt-owner-provenance-root-current-20261003-r5.patch -Leaf); SHA-256 $patchHash.
- git apply --check --whitespace=error: **PASS** against current root working tree; patch not applied.
- T08 confirmed R5 stays root-current; it will not backport to its stale receipt model. T14 gent_context.py ETag hunk is unrelated; no T08 packet overlap.

## Owner metadata

Persist owner, mutation generation, and evidence type in existing details JSON under _verification_receipt.schema=verification_receipt_metadata.v1. No SQL schema change. New writes versioned; legacy unversioned metadata remains readable only through tenant-scoped artifact validation; unknown versions fail closed. Completion picks latest receipt first, then filters visibility by task owner, preserving supersession without exposing foreign receipts.

## Files and hashes

- src/local_ai_hub/agent_verification.py: root preimage $sourceBase; candidate $sourceHash.
- 	ests/test_agent_receipt_completion_t09.py: root preimage $testBase; candidate $testHash.

Inherited T09 worktree dirt preserved, excluded from patch: gent_events.py, gent_tasks.py, project_config.py, erification_rules.py. T08-owned test files excluded. /api/context/pack untouched.

## Tests (all NOT RUN)

	est_keyword_search_respects_requested_result_bound; 	est_recording_same_receipt_twice_is_idempotent; 	est_receipt_owner_metadata_uses_versioned_existing_details_envelope; 	est_legacy_receipt_owner_metadata_remains_valid; 	est_unknown_receipt_metadata_schema_fails_closed; 	est_repo_bound_task_rejects_receipt_at_different_revision.

No T20 GO; no tests, builds, or release checks run. Earlier 9-pass receipt predates current candidate and is not acceptance evidence.