# T06 provenance and worktree runner receipt

Date: 2026-10-01
Candidate HEAD: `94337de7309b66c63ff427cce8cd3a49e6414d73`
Status: `PARTIAL; isolated safety batch passed`

## Patch and source pins

Patch: `handoff/T06-provenance-worktree-hardening-v1.patch`
Patch SHA-256: `82E554B57C31599744E2DA3014EE95C2B5DF3E85B98847FC6A2BE81EDA58392C`

Patch is a narrow T06 candidate delta. Its pre-delta source states were reconstructed by reversing only this patch's exact changes from the candidate; they are not Git HEAD or root pins.

| File | Reconstructed pre-delta SHA-256 | Result SHA-256 |
|---|---|---|
| `src/local_ai_hub/commands.py` | `7AF391442CB70FCE1E8F4248E264F2DFAB719BD310F162EA51BA5358D28B4415` | `B31909175FC4D939AE0FF1EE24F998381ED4FC4C6C8FE0068F66CC424DB64AD9` |
| `src/local_ai_hub/process_utils.py` | `7ADBA506EAAE0118844F2EDFB3AA24A2852CD5F35CCCC351CC925B947B2FFD5B` | `766D5378CD8B838D50CFA2B36B0091D30B5BCFDB620C9D37934AA3CE76D914E2` |

New T06 tests: `tests/test_t06_server_command_provenance.py` SHA-256 `8182A3B51F581D9644B2FAC9EF965E84A7B3481E85AF19199B88A7CB1A530A6D`; `tests/test_t06_worktree_subprocess_tracking.py` SHA-256 `43D15DB34E185D8DAFEFD63067765851D5A52CF8343139510A88B77CE347DF7F`.

A read-only `git apply --reverse --check` passed against the isolated candidate overlay. This proves the patch matches that overlay, not a clean root checkout. T20 owns root-base applicability and integration.

## Isolation and import origin

Test overlay: `C:\Users\Adam\AppData\Local\Temp\t06-attempt-fence-overlay-20261001-379f2e783b264c07a03004e9098755ef`.

Overlay `tests/conftest.py` asserts `commands.py` and `process_utils.py` load under the overlay's `src` directory. Preflight printed both overlay paths. No test ran from root or the task worktree; shared pytest slot was not used.

## TDD receipts

- Worktree subprocess regression failed first: `1 failed in 0.43s`; old helper called `subprocess.run` after the test replaced that escape path with an assertion. Log `%TEMP%\local-ai-hub-t06-worktree-runner-red-20261001.log`, SHA-256 `D7EBEE73F4651B54A4B3468600F86F6D1F42714CE767ABF2E672192A2996620C`.
- Cached proof and broker-ledger regressions failed first: `2 failed in 0.22s`; cache minted an artifact and broker had no lookup record. Log `%TEMP%\local-ai-hub-t06-command-proof-red-20261001.log`, SHA-256 `B10703701EA2F29116999CFE03D416406D220B39F8CAA11AA24D93EF7FA02CFE`.

## Fresh focused acceptance


Exact selectors:

`tests/test_t06_server_command_provenance.py`, `tests/test_t06_worktree_subprocess_tracking.py`, `tests/test_command_transaction_snapshot.py::test_mutating_run_requires_authoritative_fencing_before_spawn`, `tests/test_command_transaction_snapshot.py::test_private_transaction_requires_work_attempt_even_when_store_is_available`, `tests/test_command_transaction_snapshot.py::test_fenced_transaction_recovery_requires_current_work_attempt`, `tests/test_command_transaction_snapshot.py::test_expired_transaction_lease_cannot_overwrite_newer_declared_path`, `tests/test_command_transaction_snapshot.py::test_transaction_recovery_preserves_foreign_change_and_keeps_journal`, `tests/test_command_transaction_snapshot.py::test_disjoint_private_transactions_commit_only_their_declared_paths`, `tests/test_command_rollback.py::test_private_transaction_source_conflict_marks_outcome_unknown_and_invalidates_caches`, `tests/test_command_rollback.py::test_run_does_not_restore_while_process_tree_cleanup_is_unconfirmed`, `tests/test_command_rollback.py::test_execute_does_not_kill_or_reap_after_tree_cleanup_is_unconfirmed`, `tests/test_process_utils.py::test_run_hidden_timeout_kills_real_windows_descendant_after_root_exit`.Exact run: `13 passed in 20.79s`, exit 0. Run used `python -m pytest -q --tb=short -p no:cacheprovider` with both T06 test files and ten existing attempt-fence/rollback/process selectors. Stdout log `%TEMP%\local-ai-hub-t06-security-final-20261001.log`, SHA-256 `4818FCB87FBF1CCBC1EB5A83D22A7E39438678F53EB3E8EBD450CDA453136B0A`.

The batch covered broker-run record lookup and defensive copy; no cached proof minting; mutation fencing and current-attempt recovery; stale-owner rejection; journal retention; disjoint write sets; outcome-unknown cache invalidation; rollback after uncertain process-tree cleanup; and worktree subprocess routing.

`test_run_hidden_timeout_kills_real_windows_descendant_after_root_exit` ran on Windows. It confirmed the descendant exited after bounded Job Object cleanup and asserted elapsed time below 8 seconds. This is a safety result, not a performance claim.

## Implementation and contract boundary

`commands.py` records a bounded in-process server execution ledger keyed by actual broker `command_id`, after successful artifact and typed receipt persistence. Records bind tenant identity, task, owner, criterion, command hash/classification, project binding, evidence ID, repository revision, mutation generation, zero exit, and `cached=false`. Getter returns a defensive copy. Cache hits cannot mint a command proof.

`process_utils.py` routes 11 Git worktree creation, ownership lookup, list/status, cleanup, prune, and branch subprocess calls through `run_hidden`. The integration test rejects direct `subprocess.run` use inside those helpers.

Shared contract: `handoff/T06-T09-command-execution-provenance-contract-v1.md`. T09 must make completion consult the broker-issued record; public receipt submission still stores caller payload in current `agent_verification.py`. T09 owns consumer integration. Current T06 ledger is in-process and bounded to 2048 entries, so missing, evicted, or post-restart records must fail closed. Durable same-database storage remains open; no parallel verification database was added.

No T09 source/tests or root files changed. No live Docker acceptance ran.

