# T06 recovery durability root-current handoff

Generated from exact root preimages with git diff --no-index. Not applied. No tests run.

## Root preimage
- Root: C:\Users\Adam\.local-ai-hub
- HEAD: 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf
- src/local_ai_hub/commands.py SHA-256: 83CB8776B086167F1198F127E05C1271ABC9E742BA1C0684772357A0BF28A279
- tests/test_command_transaction_snapshot.py SHA-256: 69137D87698E81995014079D9E513EC327981DDA7EC81E43CCFC7231EE9A9E51
- $19B471185F14B3C1543A3B4432B258A9E1A27D084254446F45693DB4D9195F689

## Scope
Propagates False from journal persist, write-set directory fsync, and journal removal. Unsupported fsync reports recovered rollback_paths, command_not_run, and durability_warning. OSError remains recovery_required/outcome_unknown with journal retained.
Excludes T15 patch_and_verify, _snapshot_patch_targets, _restore_patch_targets, and tests/test_command_concurrency_contract.py.

## Commands
From C:\Users\Adam\.local-ai-hub, after confirming both preimage hashes:
git apply --check --whitespace=error -- "C:\Users\Adam\.codex\worktrees\t06-write-set-resume\.local-ai-hub\handoff\T06-root-current-recovery-durability.patch"
After the shared slot is released:
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_transaction_snapshot.py::test_transaction_recovery_reports_durability_outcome

## Focused diff review
- Review status: PASS for the stated recovery durability scope; no root application.
- Unsupported directory fsync: false results accumulate without skipping subsequent recovery or journal cleanup calls; return reports recovered rollback paths, command_not_run, and durability_warning.
- Real OSError: existing fail-closed recovery_required/outcome_unknown path remains; focused case asserts retryable=false, terminal=true, and retained journal after restored outputs.
- Ownership: `_recover_transaction_journals` call sites only, plus this file's parameterized regression; T15 symbols/files excluded.

## Focused test receipt
- Command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_transaction_snapshot.py::test_transaction_recovery_reports_durability_outcome`
- Intended cwd: `C:\Users\Adam\.codex\worktrees\t06-write-set-resume\.local-ai-hub` (task-owned worktree)
- Broker result: NOT RUN; `request_not_sent=true`, `outcome_unknown=false`, request_id `req_6769187e59c3`.
- Retry: none, per instruction. No test result inferred.
- Candidate patch parser: `git apply --stat` accepted two paths (commands.py: 26 changed lines; transaction snapshot test: 58 added lines).
- Root `git apply --check`: pending; root unchanged.

## Serial slot test attempt
- Command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_command_transaction_snapshot.py::test_transaction_recovery_reports_durability_outcome`
- Cwd: `C:\Users\Adam\.codex\worktrees\t06-write-set-resume\.local-ai-hub`
- Broker request_id: `req_f0e5c6736fb2`; execution_id: `8151c695586f48b199a4b62cf4091fca`; repository_revision: `3402436c49060bd82d309dfa653b5c980668ded1edb51c9cb9be8bcf76a6088a`.
- Result: exit 4; 0 tests ran; pytest error: `file or directory not found: tests/test_command_transaction_snapshot.py::test_transaction_recovery_reports_durability_outcome`.
- Slot released immediately. No retry. Patch and root preimages unchanged.

## Assigned-worktree reconciliation
- T06 worktree HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- T06 `src/local_ai_hub/commands.py` SHA-256: `92DA8EED154EB9B230832D88F341E660B6051EEC7D02B4D467AAE24922F064A8` (dirty worktree).
- Root-current commands.py preimage required by patch SHA-256: `83CB8776B086167F1198F127E05C1271ABC9E742BA1C0684772357A0BF28A279`.
- `tests/test_command_transaction_snapshot.py` is absent from the assigned T06 worktree. Bounded search found no `_recover_transaction_journals`, journal recovery tests, or recovery attempt helpers in its `commands.py` / `tests/` paths. Existing `tests/test_command_rollback.py` covers different rollback contracts.
- Therefore prior focused broker request ran zero tests (exit 4); this is worktree/preimage mismatch, not a test failure. Do not retry selector or adapt test against unrelated rollback-only source.
- Next safe step requires a registered task-owned worktree seeded with the exact root-current dirty commands.py and untracked snapshot test preimages, or an explicitly agreed root-current handoff. Root remains unmodified; current patch remains unchanged.
