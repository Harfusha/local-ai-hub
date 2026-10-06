# T09 receipt metadata and retrieval handoff

- Candidate: $w, detached HEAD $(git -C C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub rev-parse HEAD).
- Root: $r, HEAD $(git -C C:\Users\Adam\.local-ai-hub rev-parse HEAD); dirty paths pre-exist this handoff. No root writes made.
- Patch SHA-256: $((Get-FileHash -Algorithm SHA256 -LiteralPath C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub\handoff\t09-receipt-metadata-search-root-current-20261003-r3.patch).Hash).
- git apply --check --whitespace=error: **PASS** against current root working tree; patch not applied.
- Machine receipt: $(Split-Path C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub\handoff\t09-receipt-metadata-search-run-20261003-r3.json -Leaf).

Acceptance coverage added:
- 	est_keyword_search_respects_requested_result_bound: query returns at most requested limit.
- 	est_recording_same_receipt_twice_is_idempotent: repeated same receipt yields one completion receipt.
- 	est_repo_bound_task_rejects_receipt_at_different_revision: stale repo-bound receipt cannot satisfy current revision.
- Existing T09 tests cover description round-trip/indexing, indexed goal/description/criteria/checkpoint fields, foreign task/tenant isolation, stale revision, restart retrieval, and durable completion.

Privacy fix in gent_verification.py: after selecting latest receipt per criterion, completion response and consistency audit receive only receipts owned by task owner. Foreign newer receipt still supersedes old one and fails gate without disclosing foreign receipt.

Validation status:
- T20 did not grant GO; lease reported UNKNOWN. Test slot not released.
- Current candidate tests: **NOT RUN**. Prior 9-pass focused receipt predates these three tests; it is not current acceptance proof.
- /api/context/pack untouched. Root patch remains unapplied.