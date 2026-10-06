# T05 memory acceptance contract — 2026-10-01

Purpose: define remaining T05 storage proof and its T08/T09 boundaries. This is a test contract, not root acceptance.

## T05 store scope, privacy, CRUD

Root now reports four identity/delete selectors passing after correction: **4 passed in 1.49s**, root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Receipt: `t05-root-identity-delete-acceptance-2026-10-01.md`.

Candidate-only selectors still need separable root implementation and fresh root receipts:

1. `tests/test_agent_memory.py::test_find_skips_corrupt_rows_without_aborting_scoped_read` — malformed provenance/evidence rows must be skipped without aborting scoped retrieval.
2. `tests/test_agent_memory.py::test_memory_write_redacts_private_fields_and_blocks_sensitive_records` — private fields and secret assignments must be redacted; prohibited sensitive records must not persist.
3. `tests/test_agent_memory.py::test_memory_correction_lineage_and_delete_survive_reopen` — corrections preserve `supersedes_record_id`; delete and lineage remain correct after store reopen.

Candidate run for all four T05 selectors: **4 passed in 1.44s**, candidate source/test hashes `ADC4889AE9FE456CC245B5202C7E0D6CD0D897F56C3503C47B7CEEED9E797463` / `70CF1471E242DEB19E05F8E2838A6DF0E8E719C154D477A4BF27C3586957759E`. Log: `t05-memory-policy-four-selectors-green-2026-10-01.log`, SHA-256 `E03514FEC0BB9DD7745DE687EA28D60D89BBCAA410F7F03CF543D60CD01863FA`. Candidate evidence is not root evidence.

## T08 task and resume adoption contract

Use T08-owned acceptance tests; do not duplicate or edit T08 task-context implementation from T05:

- `test_create_uses_only_matching_root_and_tenant_without_saving_prompt_memory`
- `test_create_and_resume_attach_only_scoped_negative_knowledge`
- `test_resume_refreshes_memory_and_checkpoint_keeps_audit_bundle`
- `test_stale_and_expired_memory_are_skipped_with_bounded_warnings`
- `test_volatile_memory_requires_checkpoint_source_check_and_bundle_survives_checkpoint`

Required behavior: create and resume retrieve small deterministic scope-matched memory; exclude cross-root/tenant, stale, expired, or corrupt rows; never save prompts as memory; keep bounded warnings; checkpoint selected IDs/provenance or a reason for skipping; require source checks for volatile facts; preserve the audit bundle through checkpoint/reopen.

T08 artifact currently present at `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub\tests\test_agent_task_memory_adoption.py`, SHA-256 `BC6F15768EFAE901182582D9BC2EE8D204E3683EEAE24C2C7DED2FBF30009500`. Root acceptance receipt for these cases is not recorded here.

## T09 receipt boundary and shared ownership

T09 receipt persistence/completion remains separate. Its candidate task/receipt files depend on T08 transaction APIs; no T05 patch may copy those hunks into `agent_tasks.py` or verification files.

Shared paths are dirty in root: `src/local_ai_hub/agent_memory.py` (`436E90BFF060005F91F93803719D0F33DCDE9A3089731F7743273456FC619FFF`), `src/local_ai_hub/agent_tasks.py` (`A02265B88F302565904E7A20300C434DBF5BD3F11B96EB7DA60AAF6ACD5CF9DB`), `tests/test_agent_memory.py` (`FB7115C9401A66A2A5200A6424F4A31C261F233765E40DB64AE8FC94A3DF12CA`), and `tests/test_agent_tasks.py` (`A873678E065636516C537BC4193F3473A8F4B7E24BDAFC736B3703CBA2B6770F`). Do not integrate overlapping hunks without owner coordination.

T05 stays open until its three store selectors pass on root. Broader memory adoption stays open until T08's listed create/resume cases have fresh root receipts. T09 receipt gates remain T09-owned.

## Prepared separable test handoff

Test-only patch: `artifacts/t05-memory-policy-missing-root-tests.patch`, SHA-256 `3675FE22BE08B4A1DFDECDE0B27E426AF04ABF28C97EBB92670C4B9EB0D0AB08`. It adds only the three missing T05 regression tests to `tests/test_agent_memory.py` (163 lines); `git apply --check` against current root passed. It does not contain implementation changes and must not be treated as a root pass. The same three selectors passed in the candidate run listed above.

## Root T08 adoption gap

Root has no `tests/test_agent_task_memory_adoption.py`. The five T08 acceptance tests are present only in the T08 candidate module above. Root `agent_tasks.py` and `tests/test_agent_tasks.py` are dirty and overlap T08/T09; T05 must not patch them before owner coordination. No root receipt exists for create/resume adoption.

## Ownership snapshot

Read-only `git status` confirms T08 candidate has dirty `agent_memory.py`, `agent_tasks.py`, `agent_verification.py`, task/receipt tests, and the new memory-adoption test module. T09 candidate has dirty `agent_tasks.py`, `agent_verification.py`, `work_orchestrator.py`, and corresponding task/receipt tests. Root `agent_memory.py`, `agent_tasks.py`, `work_orchestrator.py`, and task tests are also dirty. T05 source hunks cannot be safely merged into shared `agent_memory.py` until owners confirm boundaries; task/resume changes remain T08/T09-owned.

Owner coordination is authorized and messages were sent to T20 and T08. T08 adoption tests and fresh root receipts remain pending from their owners; no owner-owned code was edited here. T20 reported the root test slot free for T06, but T08 has not confirmed release of its shared slot.

## Test patch correction and root-gap baseline

Use `artifacts/t05-memory-policy-missing-root-tests-v4.patch` (SHA-256 `4682B5D2FA11D20484F658DAC22D0919B2C5EC0346D517C1BA637A59DB6EE766`); it includes the required `contextlib.closing` import. Earlier v1/v2/v3 artifacts omit that import; do not apply them. The v4 patch passes root `git apply --check`.

I ran the three new test bodies against a temporary copy of current root source, with the root test module augmented in the temporary directory. Result: **2 failed, 1 passed**. Corrupt-row selector aborts with `JSONDecodeError` while parsing `evidence_ids`; private-field selector retains `api_key`, prompt/source text and secret assignment; correction-lineage selector passes. This is shadow diagnostic evidence, not direct root verification. Log SHA-256 `F5A5FB87786E63442E047586D92F8C2DF4CDABCF46805130C84F7E4FF316EF3C`.

Proposed ownership seam: T05 owns pure serialization/privacy helpers, write-boundary sanitization, and corrupt-row decode filtering. T08 owns event append ordering, cursor bookkeeping, schema, and retention. T09 owns receipt/verification/task-completion gates. Keep T05 out of T08/T09 transaction, cursor, schema, retention, and `agent_tasks.py` hunks until owners confirm the boundary.

## T08 event API boundary (owner relay)

T08 confirms ownership of `src/local_ai_hub/agent_events.py`: cursor schema/backfill, append transaction helper, ordered publication, event paging, retention deletion, and cursor bounds. T05 keeps `agent_memory.py` ownership, including the two direct event writer callsites, but must use the public T08 API there:

- call `AgentStateStore.append_in_transaction(con, event, strict_idempotency=...)` instead of direct `agent_events` INSERT/MAX(seq)/cursor logic;
- keep the current caller-owned transaction;
- enter `AgentStateStore.ordered_event_publication(con)` before `BEGIN`;
- call publisher only after `COMMIT`;
- do not duplicate cursor DDL, sequence allocation, or retention bookkeeping.

This is owner-relayed contract detail, not yet a validated T05 patch or test receipt. T09 ownership remains task description/search-index hunks; T05 must avoid T09 task/receipt changes.

## T05-to-T08 memory event integration selectors

Root already has focused tests for both T05 direct event writer paths:

- `tests/test_agent_memory.py::test_record_idempotency_is_atomic_under_concurrency`
- `tests/test_agent_memory.py::test_mark_stale_for_revision_preserves_metadata_and_emits_event`
- `tests/test_agent_memory.py::test_mark_stale_batch_rolls_back_and_repeats_idempotently`

After T05 replaces direct `agent_events` inserts with the T08 public API, rerun these exact root selectors. Add a T05 failure-injection assertion that a memory row, event row, and cursor update all roll back together; T08's generic append rollback tests do not prove the memory writer's callsite integration. Preserve caller-owned transaction and publish-after-commit ordering.

## Current handoff status — 2026-10-01

- GLOBAL retrieval contract stays tenant-filtered. Shared GLOBAL rows use tenantless provenance; tenant-owned GLOBAL rows remain private to matching tenant. Explicit GLOBAL DELETE ignores transport tenant but retains root/repository guards.
- Trusted-local boundary: `SECURITY.md` defines tenant IDs as scheduling/fairness labels, not authentication. Treat tenant matching as data selection/isolation evidence, never as proof of caller authentication; acceptance docs must preserve that distinction.
- Root fixture/identity patch `artifacts/t05-root-memory-identity-minimal.patch`, SHA-256 `0A4812A7A8218F3E8633BFDA46FD77914A3C3730983A285388247C8F1014136A`, contains only three test hunks. Root `git apply --cached --check` and reverse-check against current root both pass. T20 reports exact root HTTP/context selectors **2/2**.
- Candidate snapshot patch `artifacts/t05-owned-handoff-2026-10-01.patch` is not root-applicable as a whole; T20's root apply-check failed on overlapping paths. It is evidence of candidate state only, not integration handoff.
- After slot release, candidate overlay runs passed the original corrupt-row/privacy/lineage selectors **3/3 in 0.62s**, strengthened privacy **1/1 in 0.22s**, and bundle metadata roundtrips **2/2 in 10.25s**. T20 supplied root privacy selector **1/1**. See the detailed T05 follow-up matrix in `artifacts/t05-owned-handoff-2026-10-01.md`.
- The one `local_ai_command` submission failed before write (`request_not_sent=true`, `outcome_unknown=false`, request `req_d1b7ee853702`); user authorized native candidate-only fallback after slot release. No root test was run by T05. Current scoped sanitizer patch passes `git apply --stat`; root apply-check is unverified. Earlier boundary-test patch is superseded because it omits value/nested regression cases. No patch was applied by T05.
- Keep T05 open: the first candidate matrix returned **19 pass / 2 failures** under a full-file root T08 event overlay. The two migration failures were overlay schema mismatch, not candidate migration regressions; the candidate migration suite passed **3/3** when candidate T05 `AgentStateStore` was preserved and only the missing T08 publication APIs were shimmed in the isolated test harness. T20 reports root T05 bundle/privacy selectors pass; fresh integrated root receipts remain required for migration, identity/delete, cache isolation, durable recovery and conversion safety. T08 memory-use tests and trusted-local boundaries also lack receipts.
- T08 owns task/resume adoption, cursor schema, and event API; T09 owns receipt/completion gates. Their remaining acceptance must stay explicitly assigned to those owners, not counted as T05 proof.

## Additional T05-owned receipts — 2026-10-01

- Candidate/T08 API overlay: failure-injection row/event/cursor rollback, concurrent idempotency, stale-revision event, stale-batch rollback: **4/4 in 0.48s**. Patch `artifacts/t05-memory-write-rollback-test.patch`, SHA-256 `A0997614AC342CC655775E0E617A9DEFC5CA20908D5CFB443DC03DF6C5052424`, passes candidate `git apply --check`; current root `git apply --check` fails at `tests/test_agent_memory.py:965`. Patch remains unapplied.
- Candidate safe-learning/query selectors: model conclusion remains candidate, evidence revision metadata/idempotency, hard-capped query: **3/3 in 5.17s**.
- Candidate bounded/context safety selectors: disabled-store warning, scoped diagnostics, filter-before-candidate-limit, unsafe fallback rejection, aggregate diagnostics: **5/5 in 7.10s**.
- Create/resume memory injection, checkpoint IDs/provenance/use-or-skip reason, bounded stale/expired warnings and volatile source checks remain T08-owned. No T08/T09 task-context implementation was edited in T05. T20 reports root T05 bundle/privacy pass; integrated root receipts for the remaining T05 matrix are still required.

Current T08 API overlay results are recorded in `artifacts/t05-owned-handoff-2026-10-01.md` under “Current T08 API overlay”. T05-specific privacy, rollback, and global delete passed 3/3. Broader T05 matrix passed 19/20; sole failure was candidate cache ResourceWarning on app teardown. T08 adoption with T05 memory passed 4/5; its sensitive fixture conflicts with T05's intentional persistence rejection. T20 has the exact results and fingerprints; no root test ran here.

Follow-up 2026-10-01: T08 adoption fixture now seeds the legacy sensitive record directly into durable tables, without calling the prohibited public writer or changing assertions. With T05 `agent_memory.py` overlaid on T08 task/event code, all five adoption selectors passed in 3.99s. This supersedes the earlier 4/5 fixture-conflict receipt. Fixture SHA-256: `361F89CBE401B76EC2E50482169942A4DCC68A3F5412ABDFF7FA2F32270F36C0`.

T07 fixture follow-up: one-line setup change in `tests/test_agent_state_transport.py`, hash `83A61B134D31CA53677023342BCE165A1BD3461C43AAC71907DFDB45045096BE`; targeted selector passed 1/1 in 9.36s, assertions unchanged. Full T05 `tests/test_agent_memory.py` passed 37/37 in 23.67s with verified T08 `agent_events.py` and `sqlite_support.py` overlay. T05 source/test hashes: `EBDA97B0735FC7B65682AFCFE95AE3214789F06A70818EDD38823AF867C8334F` / `6CB02CD0EF821F43AD1A30B12A891EC6A74D475B42BFDB06FA1ECF2684D8DAC2`.

## Root-current follow-up — 2026-10-01

After T02 released the shared slot, the exact root-current batch for the three formerly candidate-only memory selectors, four identity/delete selectors, nine identity/shared-memory contracts, and current-evidence contract passed **24/24 in 4.34s** on root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. This supersedes earlier statements that those listed root selectors lacked fresh receipts. Exact argv and source/test fingerprints: `artifacts/t05-root-identity-shared-memory-receipt-2026-10-01.md`. No root files were written; T05 released the test slot back to T02.

## T05 scoped completion receipt — 2026-10-01

The exact combined command is `python -B artifacts/t05-run-root-overlay-acceptance.py`; result **43 passed in 19.59s**, exit 0. It uses byte-identical root test snapshots and verifies actual root module imports; only the scoped AgentMemory tenant-delete fix runs from a temporary source overlay. Root HEAD stays `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Detailed selector, source, and test hashes are in `artifacts/t05-root-current-stepback-audit-2026-10-01.md`.

Root-current patch artifacts, all `git apply --check --whitespace=error` clean: scoped tenant-delete source/test `876CEF0B2CCA7E253BC1DDAFA2A5C16F6906A1BCBF3831807608344DD8DFD52D`; cache child source proof `C3966647EA97BD26DED761705BD8393756FC5DC098145EDE40979C718EBD6A84`; migration backup/DDL fault tests `E9D5C58A6173F8FEE2EE113B36AF4BCA2B9139E8DD8197E43A6A2D795A2AB8F4`; HTTP stale-identity test `DEC2A091C4782ED474EFBB365D54FC4BB1642F677477C6C14A2671C6F8B52C05`. D1/D4 source changes are already present in root; their selectors pass in the combined receipt. Root was not written by this task. T08 lifecycle/fencing and T06 concurrent cache recovery remain outside this T05 patch set.
