# T06 root-current acceptance manifest v1

Date: 2026-10-01
Worktree: `C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub`
Candidate HEAD: `94337de7309b66c63ff427cce8cd3a49e6414d73`
Status: `PARTIAL / NARROW ISOLATED RECEIPT`

This manifest collects existing receipts and pins for T06 handoff. It does not create new test evidence. T20 owns root integration and root validation. Do not apply candidate changes to the root checkout from this worktree.

## T09 receipt contract selected

Use the current T09 typed proof and receipt shape, as approved by the user:

- Test and benchmark completion use T09's typed receipts.
- Lint/source proof uses `work_command_verification` with a `source_review` receipt.
- V8 preserves configured alias/configuration/argv/environment binding when a project rule matches. Generic actual test evidence is allowed only when no matching rule requires configured proof; a matching rule suppresses generic evidence.
- No separate `command_kind` or extra hash/alias receipt schema is introduced here. T09 remains owner of receipt consumption and durable evidence; T20 remains owner of root integration.

Contract: `handoff/T06-command-proof-contract-v3.md` (SHA-256 `93E5AE869528D2F91EFDFABFD072898BD64D6CC5E9D53E10FA2C21DEAEC8D81D`).

## Root-current V8 identity

| Item | SHA-256 / identity | Evidence state |
|---|---|---|
| Root base `commands.py` | `39E92B34A7185C2DBC3F38BCF507627276B049BB9A5D145EAD7C9574A87D949E` | Prior T20-owned pin; not reread here |
| V8 patch `handoff/T06-T09-validation-receipts-v8-root-namespace-current.patch` | `B8925B9A3542164AA4FCF29B073DD35048E86E39BDD49E561812367C37191F60` | Candidate; root not modified |
| Result `commands.py` | `4814FA5E1868D58961C674533D0F7A0021389A84487F206CC926CA2B1C21CF69` | Patch target pin |
| Current T06 `src/local_ai_hub/commands.py` | `31785DD1C3858705B6553B51388D059573D0768BFDBD15F1E0F213D07F86AAD4` | Different candidate file; later T06 edits, not V8 result |

V8 overlay receipt: `tests/test_t06_project_validation_receipts.py` returned `2 passed`; targeted `pyflakes` on produced `commands.py` passed; `git apply --check` passed against the pinned root base. Builder applied the patch to a temporary root-package copy. The two regression cases failed against v7: raw `pytest -V` and pytest `addopts=--collect-only` could mint receipts. These are overlay receipts, not root-current integration receipts. No persistent stdout log was located for the two-test run.

## Existing T06 receipts

Historical receipts below predate later work-attempt-fence edits. They prove their logged candidate state only; they do not validate current hashes above. The current consolidated overlay receipt is `handoff/T06-targeted-security-receipt-20261001.md`; it covers attempt fencing, rollback uncertainty, cache provenance, worktree subprocess routing, and descendant cleanup. The earlier `handoff/T06-attempt-fence-isolated-receipt-20261001.md` is historical and superseded for the newer `commands.py` hash.

| Scope | Result | Receipt |
|---|---|---|
| Rollback, cache invalidation, timeout cache contract, auxiliary policy, daemon lifecycle, process utilities | `155 passed, 6 skipped, 48.15s` | `%TEMP%\local-ai-hub-t06-safety-final-20260930.log`; SHA-256 `1922D97F966839BB468F9E064B93A118CBFF45A8B799091BEB458CEEC3FA3AA5` |
| Focused rollback/cache/policy/daemon selectors | `10 passed, 1 skipped, 4.54s` | `%TEMP%\local-ai-hub-t06-focused-20260930.log`; SHA-256 `458677FEF7EDEAC4CF1BC22021B556E8179C798730E2A196649055214EEFA400` |
| Explicit write-set and repair-loop guards | `4 passed, 1.72s` | `%TEMP%\local-ai-hub-t06-write-set-selectors-20260930.log`; SHA-256 `184A7CE10D98E06D8F6DB453079B6FD5D27449083E6C6917B96F9BC832E963E9` |
| Transaction snapshot focus | `19 passed, 30.74s`; logged command line not embedded | `%TEMP%\local-ai-hub-t06-transaction-focus-20261001.log`; SHA-256 `B4B542A36F098254264467FC0276E96DF90CB35F558D459EA96FFC9EB31700A3` |
| Assigned snapshot/broker batch at candidate HEAD | `159 passed, 7 skipped, 2 failed, 52.63s` | `%TEMP%\local-ai-hub-t06-next-slot-20260930.log`; SHA-256 `AFE79F5FE2D4F1B944B52A4CA6DEE68EDD443A0110FE81730E3195044C85C3CC`; both failures were `.gitignore` snapshot races |
| Focused replay integration | `45 passed / 26.26s`; narrow classifier/policy subset `25 passed / 7.31s` | Plan checkpoint only; no log path/hash located. Do not use as exact per-selector evidence. |

The older `155` and `19` receipts are stale for current candidate. Later work-attempt-fence and provenance edits changed broker and process utility files. The plan did not cover those edits. The fresh 13-test overlay receipt pins current sources below.

## Current candidate pins

| Path | SHA-256 |
|---|---|
| `src/local_ai_hub/commands.py` | `B31909175FC4D939AE0FF1EE24F998381ED4FC4C6C8FE0068F66CC424DB64AD9` |
| `src/local_ai_hub/process_utils.py` | `766D5378CD8B838D50CFA2B36B0091D30B5BCFDB620C9D37934AA3CE76D914E2` |
| `src/local_ai_hub/command_transactions.py` | `CFFC36198FD402754E9F4B2BAC4472351FC9313AB5EC65BB1D6A6FCC95CE86FA` |
| `tests/test_command_transaction_snapshot.py` | `1F1D9EBF17A86BB1A957C3EF2A73FED26780A982BB7A5888726ABC2F424A989E` |
| `tests/test_t06_server_command_provenance.py` | `8182A3B51F581D9644B2FAC9EF965E84A7B3481E85AF19199B88A7CB1A530A6D` |
| `tests/test_t06_worktree_subprocess_tracking.py` | `43D15DB34E185D8DAFEFD63067765851D5A52CF8343139510A88B77CE347DF7F` |
| `tests/test_command_rollback.py` | `F3F5D06C3AA3C8EC2A23E34E6BA3ABDB658981B4DF6437AA92363EB0C51D0CB6` |
| `tests/test_daemon_lifecycle_hardening.py` | `A90ED80455E755A47AF266F4B3E9323120DA69F94E5543B107ECA726C7663FED` |
| `tests/test_t06_project_validation_receipts.py` | `229F76D40205048A27258DD12F08F8ADD34CDDB7D194B4C23337876D06563942` |

## Acceptance still open

- **Current-source focused pytest:** 13 targeted selectors passed in an isolated copy; see `handoff/T06-targeted-security-receipt-20261001.md`. Shared slot was not used. Full focused suite remains unrun.
- **Attempt fencing:** fresh receipt covers stale owner rejection, current-attempt recovery, retained journal on foreign conflict, and unknown/cache invalidation. Dedicated attempt-renew timeout/cancel outcome and durable production-store behavior remain unverified.
- **Broker boundary:** current candidate tests define private snapshot, declared import, undeclared-output rejection, enforced Docker boundary, authoritative fencing, and required work-attempt cases. Existing receipts do not cover the full latest broker path. Required nodes include `test_mutating_run_executes_private_snapshot_and_imports_declared_output`, `test_mutating_run_rejects_undeclared_transaction_output`, `test_mutating_run_requires_enforced_docker_boundary_before_spawn`, `test_mutating_run_requires_authoritative_fencing_before_spawn`, `test_private_transaction_requires_work_attempt_even_when_store_is_available`, `test_transaction_recovery_completes_outputs_from_persisted_journal`, `test_transaction_recovery_preserves_foreign_change_and_keeps_journal`, and `test_expired_transaction_lease_cannot_overwrite_newer_declared_path`.
- **Windows live isolation:** Docker engine pipe and `python:3.11-slim` image were unavailable in prior checks. A skipped or stubbed Docker run is not acceptance.
- **Platform coverage:** POSIX daemon/process-tree and locking cases skip on Windows; those behaviors lack Windows-equivalent live proof where applicable.
- **Command proof provenance:** T06 now records successful broker executions in a bounded private in-process ledger and skips cached proof minting. T09 must make completion consult that record; public receipt ingestion still accepts caller payload. Durable same-database record and consumer enforcement remain open. See `handoff/T06-T09-command-execution-provenance-contract-v1.md`.
- **Root integration:** V8 patch remains a handoff candidate. T20 must verify exact base pin and integrate/validate in root-owned context.

## Ownership and freshness

No root checkout file or root test changed in this manifest turn. The working tree already contains T06-owned edits. The manifest is documentation only. Existing old plan text includes historical statements that differ from the current candidate; use current file pins and the isolated receipt for handoff. Do not report T06 complete from narrow receipts.




