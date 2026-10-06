# T16 acceptance matrix v1

Scope: candidate worktree `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub` only. Root integration and root validation remain T20-owned.

## Sealed candidate receipts

| Acceptance slice | Exact selector / evidence | Receipt | Source pin |
|---|---|---|---|
| Terminal revival | `tests/test_t16_terminal_rollback_preflight.py::test_delayed_worker_does_not_claim_or_execute_after_successor_terminal_state`; `::test_fresh_attempt_cannot_rewrite_terminal_work_state` | Module receipt: `12 passed, 1 skipped` in 5.09s. Terminal rows stayed immutable; delayed worker made no service call or attempt claim. | `tests/test_t16_terminal_rollback_preflight.py` SHA-256 `041E3B08B3E2E53B9880781427C51C2E785B3D00B6A4B882D8D2B4D6E97B1403` |
| Cross-process namespace fencing | `tests/test_t16_cross_process_namespace_lease_recovery.py::test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit` | Isolated child-process receipt: `1 passed` in 9.76s. Proves A/B shared conflict, C isolation, persisted expiry/reclaim, monotonic fences, stale write/commit rejection, wrong-owner renew/release. | `tests/test_t16_cross_process_namespace_lease_recovery.py` SHA-256 `4E727AB7D2FF32A943912CE414A08015E6F719293440BD224C8165CF72310C1F` |
| Cross-process physical root scope | `tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens` | Fresh three-process receipt: `1 passed` in 0.40s. Old, successor, and stale holder reopen same SQLite DB; all attempt/lease scopes equal canonical physical root; successor tokens exceed stale tokens; stale process cannot write file or fixture commit receipt. | Candidate `tests/test_work_fencing.py` SHA-256 `022A63AC48C44473416FB5CEF252748111240538B5C06C05E5778D3175B4F31F`; root-current test-only patch SHA-256 `F11D8B8D276815738867CABB55ACF490B3846A611F4AE77BBC58071AEB9AD2B5` |
| Failed commit/write | `tests/test_work_handoff_acceptance.py::test_partial_git_apply_failure_restores_all_preimages_and_clears_journal` | New bounded fault-injection receipt: `1 passed` in 0.65s. Apply writes first target then reports failure; rollback restores both preimages and clears in-memory and persisted journal. | `tests/test_work_handoff_acceptance.py` SHA-256 `0DEE55FF094513A23311CDE0B9E1B38364999DAEC06A50FFE0A8998B00D6F42C` |
| Trusted namespace: four store APIs | `tests/test_t16_http_lease_routes.py::test_http_lease_routes_resolve_namespace_and_isolate_linked_worktrees` | Current focused candidate receipt: `1 passed` in 5.24s. Exercises `claim`, `claim_batch`, `list`, and `waits`; HTTP request identity comes from server `ProjectContext`, forged payload identity is ignored. | Test SHA-256 `D560EC58FD1250881D6D9241D6B2C6CE8A0E119F87B1C9C1CE809D97954363C2`; route patch SHA-256 `954F126E34DC408F2AF8139E54033F88967EDC2DC072E94F627D70360CCC3AFE` |
| Explicit write-set lifecycle after SQLite reopen | `tests/test_t16_explicit_write_set_lifecycle.py::test_explicit_namespace_write_set_stale_owner_cannot_commit_after_sqlite_restart` | Root-derived temp overlay receipt: `1 passed` in 0.46s. Three subprocesses reopen same store; expired `team-shared` lease reacquired; independent `team-isolated` namespace shares path; out-of-scope and stale commits rejected. | Root `work_fencing.py` SHA-256 `4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050`; test SHA-256 `CA9021A1FC1B3619CC7FCE59A08C321354EDD39F576B7D991FF312D3C54B3A7A`; root-current patch SHA-256 `5450DD3899805107F20721D7BB4FC600E9F58582B604847364BC719C1912AF83` |
| Windows junction/reparse containment | `tests/test_work_fencing.py::test_rooted_scope_resolves_junction_alias_to_same_path`; `tests/test_t16_terminal_rollback_preflight.py::test_rollback_rejects_junction_before_restoring_any_file` | Current-root-worktree overlay: `2 passed in 0.21s`. `mklink /J` worked without elevation; internal junction passed containment yet rollback refused it before any restore. | Test-only patch SHA-256 `C53136D6B06E7A90BE168F03BFF2D4132004C8CA4564119C090F215733872E1A`; root preimages recorded in `T16-windows-junction-acceptance-root-current-v1.md` |
| Orchestrator → LocalAIServices → T06 broker handoff | `handoff/T16-orchestration-broker-handoff-acceptance.py::test_work_orchestrator_validation_reaches_real_broker_with_fence` | T06/T16 compatibility overlay: `1 passed in 2.26s`. `WorkOrchestrator` wired its fencing store into T06 `CommandBroker`; `LocalAIServices` ran real `git diff --check`; stale mutating `git add` was refused before transaction spawn. | Fixture SHA-256 `A5472294E010E15D3C3FEA4CD19A82C3070B8279A858C603DD5026892FFE60CF`; T06 `commands.py` SHA-256 `B31909175FC4D939AE0FF1EE24F998381ED4FC4C6C8FE0068F66CC424DB64AD9`; T16 `services.py` SHA-256 `B1F1E117F49D566E067257E90868CD4134B736C1D3F49A783DC4EDE79BE9C97E` |

Core namespace/fencing patch pin: `T16-namespace-root-current-v5.patch`, SHA-256 `27242C3C4F9EA7113DC9E84C4179A6E937583175BF4ECEA64D605BC34A940459`.

Earlier sealed candidate batch: `68 passed, 1 skipped, 1 deselected` in 57.32s, before latest root-scope receipt enhancement. The deselection is T06-owned broker coverage. The Windows directory-symlink skip (`WinError 1314`) remains an explicit unverified platform gap.

Earlier registered-candidate T16 batch at HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py tests/test_work_orchestrator.py tests/test_work_handoff_acceptance.py tests/test_t16_project_namespace_leases.py tests/test_t16_http_lease_routes.py tests/test_t16_cross_process_namespace_lease_recovery.py tests/test_t16_terminal_rollback_preflight.py tests/test_t16_lease_wait_namespace_isolation.py tests/test_t16_explicit_write_set_lifecycle.py -k 'not command_broker'` — `72 passed, 1 skipped, 1 deselected in 48.02s`, exit 0. Skip: Windows directory-symlink `WinError 1314`. Deselection: T06-owned broker selector. Superseded by the 2026-10-02 fresh batch below.

Root-current portable overlay: [latest receipt and post-integration gates](T16-root-current-portable-overlay-v2.md), SHA-256 `8A0F996A58E2A766931BBC548AB5CE009DEB681FD2591946F09557A67B020601`. Root HEAD source pins; `55 passed, 1 skipped, 8 deselected` in 18.76s. T16 orchestration/handoff tests pass with baseline services/http and T21 seam shim. Current T16 services/http integration remains gated by `vision_contracts.image_dimensions`; ProjectContext identity selectors and T06/T09 owner gates excluded.

Current root-working-tree overlay with actual T06 CommandBroker: [cross-process and broker receipt](T16-cross-process-broker-root-worktree-overlay-v1.md), SHA-256 `14BABD2826FA381EFDDBB8101DE335E8D05342985DC5BEFE99F51DCD6D587280`; exact five selectors `5 passed in 9.75s`. Overlay copied current root working bytes plus T16 tests; no root test/write. Actual broker forwarding and stale-attempt refusal covered.

Additional broker receipt: [orchestrator broker handoff](T16-orchestration-broker-handoff-t06-compat-v2.md). Isolated overlay combines pinned T06 broker sources with current T16 orchestration/services; it is not root integration. Candidate checkout alone still lacks T06-owned broker APIs, so fixture remains under `handoff/`, outside candidate pytest collection.

Windows junction acceptance: [root-current test patch and receipt](T16-windows-junction-acceptance-root-current-v1.md), patch SHA-256 `C53136D6B06E7A90BE168F03BFF2D4132004C8CA4564119C090F215733872E1A`. Directory junction/reparse guard passed without admin. Symbolic directory symlink selector still skips on `WinError 1314`; symlink-specific behavior remains unverified.

Combined current-root-worktree overlay: junction alias, rollback reparse refusal, cross-process contenders, physical-scope stale holder, linked-worktree namespace reclaim, explicit write-set lifecycle, and actual T06 broker forwarding — `7 passed in 12.30s`, exit 0. Exact selectors match these seven rows above; symlink selector intentionally omitted after its fixture-only `WinError 1314` receipt. Root source pins are in `T16-cross-process-broker-root-worktree-overlay-v1.md`; junction test patch pins are in `T16-windows-junction-acceptance-root-current-v1.md`.

## Root boundary

Relayed pre-fixture root batch was `98 passed, 13 failed, 1 skipped`; T20 later reported fixture API/import corrections. No fresh root receipt was supplied to this task. Do not infer root acceptance from candidate receipts. No root tests or edits were made here.

## Missing bounded regression added

The partial-`git apply` failure selector above covers a workspace write followed by command failure: expected postimages are journaled before mutation, restored under fencing, and journal cleared only after restoration succeeds. No production code changed for this coverage addition.

## Overall status

Candidate slices above are green. Full T16 acceptance remains open pending T20 reconciliation of the root-current broker patch and root-owned acceptance, plus Windows symlink capability evidence.

Root-current test-only handoff: [patch](T16-partial-apply-failure-root-current-v1.patch), SHA-256 89C3C954C4D0CCF2EAAF09D2CA9F742AE20080D36FE4DC7E5BEA5BFFE8B7A081; root test preimage pin 247A15B6D6DEB7567B857205D90ABE894BC3F5D6B97C439E94C902B6BF11CB59. Strict root apply-check passed; no root write/test.

Root-scope subprocess patch: [manifest](T16-root-scope-cross-process-root-current-v1.md), [patch](T16-root-scope-cross-process-root-current-v1.patch); SHA-256 F11D8B8D276815738867CABB55ACF490B3846A611F4AE77BBC58071AEB9AD2B5; root test preimage pin BE4123741CA0EFC66D9196FE2ED79F307ADC925CCF6CA78822C6C149ED9C97DB. Strict apply-check passed, test-only. Candidate selector receipt 1 passed in 0.40s.

Explicit write-set lifecycle: [manifest v2](T16-explicit-write-set-lifecycle-root-current-v2.md), [patch v2](T16-explicit-write-set-lifecycle-root-current-v2.patch); SHA-256 `5450DD3899805107F20721D7BB4FC600E9F58582B604847364BC719C1912AF83`. Root-derived isolated overlay only; no root write/test.

Fresh registered-candidate acceptance selectors after latest handoff: `7 passed in 7.40s` at HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Superseded by fresh 72-pass batch above. Candidate only; neither receipt proves root/T20 integration.

## Resume checkpoint — 2026-10-01

- Candidate worktree ownership/status rechecked: HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`; inherited dirty T16/T21/T06 files preserved. T21 `project_config.py`, T06 `commands.py`, and T20 root untouched.
- T16-only test change: moved `test_process_crash_after_patch_write_recovers_from_persisted_journal` from module EOF into recovery-test cluster; child process now disables `_ensure_workers` before orchestrator construction, preventing background-worker race during crash simulation. Assertions unchanged.
- Exact candidate run after final test edit: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal` — `1 passed in 1.04s`.
- Candidate `tests/test_work_handoff_acceptance.py` SHA-256: `75F7B4AD282AC28257527FDEC1B6B3755F3DB471F52BC426C24B3F6336A66208`.
- Root/candidate extracted `_recover` SHA-256 matches: `01C0320257C53A10E4239E0DD08FAE8759524963BE959E1A69C9FD123D1D544C`. `_ensure_workers` SHA-256 matches: `A6D7C173F5B82876A68E4C7474148B2528C8B6A2919F2CEE39EF8FE8947B14A6`. Earlier root `failed` result traced to child test worker setup mismatch, not recovery transition.
- T20 reported root crash selector: `1 passed in 1.15s`. Full T20-owned seven-test root selector remains pending; no duplicate root test run here. Prior T16 broad candidate batch receipt (`72 passed, 1 skipped, 1 deselected`) predates this test-only edit; only focused affected test rerun.
- Root-current placement-only patch: `handoff/T16-root-current-crash-test-placement-v1.patch`, SHA-256 `E3CC3A615D87DC4DAAF94FD4BDE1488F7E8CCC75CDAD108F8D31C8ABB6F7044A`; optional now that root crash selector passes. Do not apply if root preimage hash differs.
- Goal API still reports `blocked`; no completion claim. Hub unavailable; existing acceptance receipts retained, no Hub retry.

## T20 root selector update — 2026-10-01

- T20 latest task snapshot reports T16 root fencing/recovery selector: `7 passed / 2.10s`. Root test not rerun by T16. T20 owns exact command and root receipt; asked for selector/pins, no rerun requested.
- This updates the earlier matrix statement that no fresh root receipt was supplied, for the focused fencing/recovery selector only. It does not establish full root/T20 release acceptance.
- Root/candidate `_recover` and `_ensure_workers` method hashes match; prior root `failed` state traced to missing worker suppression in the candidate child fixture. Candidate now has same suppression and its exact test passes.
- Remaining T16 evidence gap: symbolic directory-symlink selector is still skipped (`WinError 1314`); junction/reparse selectors pass. Keep T16 goal blocked/open until this explicit platform gap is resolved or acceptance owner records approved disposition. T20 release also remains open for unrelated owners.

## Root-current exact scoped receipt — 2026-10-02

- T20 supplied exact root selector and root pins in its acceptance receipt. Result: `7 passed in 2.10s`; T16 did not rerun root suite.
- Exact selector: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py::test_commit_guard_revalidates_path_and_attempt_tokens_before_commit tests/test_work_fencing.py::test_commit_guard_rejects_expired_parent_attempt tests/test_work_fencing.py::test_expiry_reacquire_fences_stale_write_and_commit_without_side_effects tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal tests/test_work_handoff_acceptance.py::test_recovery_requeues_after_crash_between_journal_clear_and_state_update`.
- Root HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Pins: `work_orchestrator.py=CBCCC148…E78337`, `work_fencing.py=C93C2221…ECBDD0`, `services.py=CCD292C8…4564A0`, `test_work_fencing.py=64115A4B…8C9B6`, `test_work_handoff_acceptance.py=896EC91B…7A5C4`.
- Exact placement-only handoff patch `T16-root-current-crash-test-placement-v1.patch` SHA `E3CC3A61…F7044A`, root test preimage SHA `896EC91B…7A5C4`; read-only `git apply --check --whitespace=error` passed. No root write.
- Candidate crash test after worker-start isolation and recovery-cluster placement: `1 passed in 1.04s`; current test-file SHA `75F7B4AD…6A66208`.
- Symbolic directory symlink remains `NOT TESTED` (`WinError 1314`); T16 goal stays blocked pending disposition.

## Cross-process writer/commit race — 2026-10-02

- Added T16 multiprocessing regression `tests/test_work_fencing.py::test_cross_process_successor_cannot_supersede_writer_inside_commit_guard`; writer remains under `commit_guard` while an expired successor tries to claim. Final evidence: entire fencing module `12 passed, 1 skipped in 2.67s`; symlink fixture skip is `WinError 1314`.
- Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py`.
- Candidate `work_fencing.py` SHA `287DA1CD…ED2F214`; candidate `test_work_fencing.py` SHA `1A2F8F34…C358807`.
- Root-current test-only patch `T16-root-current-cross-process-commit-race-v1.patch` SHA `CFCFF000…27A4F66`; root preimage test SHA `64115A4B…3DB88C9B6`; read-only apply-check PASS. Root was not written or retested by T16.
- T16 remains open pending symlink test disposition.

## Candidate junction rerun — 2026-10-02

- Dirty provenance checked in `t16-orchestration-recovery` worktree: inherited tracked edits and untracked files preserved. `tests/test_t16_terminal_rollback_preflight.py` is untracked; its T16 junction assertion now expects the implementation's `RuntimeError` while retaining the refusal-message and no-partial-restore assertions. No root files changed.
- Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t16_terminal_rollback_preflight.py::test_rollback_rejects_junction_before_restoring_any_file tests/test_work_fencing.py::test_rooted_scope_resolves_junction_alias_to_same_path`.
- Candidate result: `2 passed in 0.22s`. This verifies rollback refusal before restore and independent junction alias normalization.
- Candidate `tests/test_t16_terminal_rollback_preflight.py` SHA-256: `F7166F3BEB4D2964AB0C9F3D4EBDCE2A3E0B257D0D6A02CAD0690DE360F15771`.
- Symbolic directory symlink remains `NOT TESTED`; Windows returned `WinError 1314` without the required privilege. Junction coverage does not substitute for symlink coverage; T16 remains open pending disposition.

## Cross-process atomic lease lifecycle and recovery — 2026-10-02

- Added `tests/test_t16_cross_process_namespace_lease_recovery.py::test_cross_process_lease_refresh_and_release_survive_sqlite_reopen`. Process A acquires the persisted lease; process B reopens the shared SQLite store, renews it, and releases it; process C then claims the same path. Test checks expiry extension and released row count.
- TDD RED was expected: before adding the child mode, selector failed with `unknown mode: refresh_release`. After the test-only harness mode was added, selector passed (`1 passed in 1.66s`). No production lease code changed.
- Exact final acceptance command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t16_cross_process_namespace_lease_recovery.py::test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit tests/test_t16_cross_process_namespace_lease_recovery.py::test_cross_process_lease_refresh_and_release_survive_sqlite_reopen tests/test_t16_explicit_write_set_lifecycle.py::test_explicit_namespace_write_set_stale_owner_cannot_commit_after_sqlite_restart tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal tests/test_work_handoff_acceptance.py::test_recovery_requeues_after_crash_between_journal_clear_and_state_update tests/test_work_handoff_acceptance.py::test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit`.
- Exact result: `7 passed in 7.04s`. Covers cross-process claim/conflict/reclaim, successful renew/release after SQLite reopen, release visibility to a successor process, stale write/commit rejection, monotonic tokens, and crash/recovery selectors.
- Candidate `tests/test_t16_cross_process_namespace_lease_recovery.py` SHA-256: `57D65635171198D378F74B34440B2892373C029FB1A9280AB51256D7DD046831`. Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Full test-file add patch: `handoff/T16-cross-process-namespace-lease-recovery-v2.patch`, SHA-256 `B82ED20A0CE6849E59C882D015DCDCBE235A5E22A207D9A99028A1256430B048`; use it instead of v1 for this path, never both.
- Symlink remains `NOT TESTED` (`WinError 1314`). Root/T20 and T06/T08/T09-owned source files were not modified.

## Fresh coordination/orchestration candidate batch — 2026-10-02

- Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py tests/test_work_orchestrator.py tests/test_work_handoff_acceptance.py tests/test_t16_project_namespace_leases.py tests/test_t16_http_lease_routes.py tests/test_t16_cross_process_namespace_lease_recovery.py tests/test_t16_terminal_rollback_preflight.py tests/test_t16_lease_wait_namespace_isolation.py tests/test_t16_explicit_write_set_lifecycle.py -k 'not command_broker'`.
- Exact result: `79 passed, 1 skipped, 1 deselected in 71.38s`, exit 0. Included the new cross-process refresh/release regression. Skip is directory-symlink creation (`WinError 1314`); deselection is T06-owned broker coverage.
- Candidate HEAD remained `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. No source files owned by T06/T08/T09 changed; root/T20 untouched. Owner-specific broker and symlink gates remain open.

## Root-current orchestration patch decomposition — 2026-10-02

- Read-only root identity: HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Current root working-tree modifications preserved.
- Root `git apply --check --whitespace=error` passed for `T16-root-current-cross-process-atomic-lease-v1.patch` (`A2B836F28FEBF4043E06AB83FE2AA70D1A769727BDFDF1D2D6B8C2EDC1998574`), `T16-root-current-cross-process-commit-race-v1.patch` (`CFCFF000F6FD1C3F1A3434B2B21BD8BB61AC5930A33D1B9AAB82C5BB027A4F66`), and `T16-root-current-crash-test-placement-v1.patch` (`E3CC3A615D87DC4DAAF94FD4BDE1488F7E8CCC75CDAD108F8D31C8ABB6F7044A`). None applied.
- Manifest: `handoff/T16-root-current-orchestration-manifest-v1.md`, SHA-256 `A3D1910D8C3E6545F0950EBB94E0FEF31714DF1B441C7E7BA23ED31140B32BD4`. It records exact root/candidate pins and excludes broad source overlays where root T20 bytes diverge.
- No root writes or tests. Root/T20 and T06/T08/T09 owner state remains intact; only test-only root-current deltas are packaged. Source integration remains with its owners.

## Root T16 postimage batch — 2026-10-02

- T20 reported the three test-only patches applied. Read-only root SHA-256 postimages and the exact pending root 3-selector command are recorded in `handoff/T16-root-current-postimage-manifest-v1.md`.
- Same 3 selectors passed in candidate: `3 passed in 3.83s`. Root selectors remain pending T20 slot release; this is not root acceptance.
- `services.py` root/candidate hash drift, symlink privilege skip, and T06/T09 ownership exclusions remain separate gates.

## T16 resume dirty-state verification — 2026-10-02

- Candidate dirty pins and root test postimages rechecked read-only; values still match `T16-root-current-postimage-manifest-v1.md`. Inherited candidate changes preserved.
- Fresh candidate run of the exact root 3-selector batch: `3 passed in 5.60s`, exit 0. Root selectors remain pending T20 slot release; no root test or write occurred.
