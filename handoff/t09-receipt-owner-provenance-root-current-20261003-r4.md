# T09 owner provenance / receipt visibility — root-current handoff

## Minimal interface proposal

- Preserve receipt owner provenance in the existing gent_verification_receipts.details JSON envelope: _verification_receipt.schema = verification_receipt_metadata.v1, plus owner, evidence type, and mutation generation.
- No SQL column, table, or migration. This is an explicit versioned JSON contract, not an unversioned sidecar expansion.
- New writes persist v1. Legacy unversioned metadata is read as legacy v0; it can satisfy completion only through existing tenant-scoped artifact validation. Unknown versions fail closed and stay hidden.
- Completion chooses newest receipt per criterion first. It then checks owner and evidence validity, so a newer foreign/invalid receipt supersedes an older pass and is not exposed in result/audit.
- Root-current code already validates proof artifact tenant, owner, task, revision, and mutation generation. T08 candidate currently lacks receipt owner and artifact-store seam; T08 response/merge is pending. No T08 checkout files touched.

## Candidate and patch

- Root: $r, HEAD $(git -C C:\Users\Adam\.local-ai-hub rev-parse HEAD).
- Candidate: $w, detached HEAD $(git -C C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub rev-parse HEAD).
- Patch: $(Split-Path C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub\handoff\t09-receipt-owner-provenance-root-current-20261003-r4.patch -Leaf); SHA-256 $patchHash.
- git apply --check --whitespace=error: **PASS** against current root working tree; patch not applied.

Changed paths and hashes:
- gent_verification.py: root preimage $sourceBase; candidate $sourceHash.
- 	est_agent_receipt_completion_t09.py: root preimage $testBase; candidate $testHash.

New tests (not run):
- 	est_keyword_search_respects_requested_result_bound
- 	est_recording_same_receipt_twice_is_idempotent
- 	est_receipt_owner_metadata_uses_versioned_existing_details_envelope
- 	est_unknown_receipt_metadata_schema_fails_closed
- 	est_repo_bound_task_rejects_receipt_at_different_revision

No tests run; T20 GO absent. /api/context/pack untouched. Root unchanged by this handoff.