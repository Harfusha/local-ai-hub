# T09 next-test handoff — 2026-10-04

## Goal and scope

T09 master-plan goal: verification receipts, worktree ownership, and evidence. This candidate owns the receipt-verification slice. T09 integration remains with the orchestrator after exact preimage and lease review.

## Candidate pre-run identity

- Checkout: `C:\Users\Adam\.codex\worktrees\t09-root-current\.local-ai-hub`
- HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Source `src/local_ai_hub/agent_verification.py` SHA-256: `A1EF1BBB5BCAEC37CB7AFB9B3088C7C5EB116DE5166A0C7B4E9806DAD8C6F71D`
- Selector `tests/test_agent_verification.py` SHA-256: `044557FCCB5B244E8F4631F648A354CB6CD0367738BBF90CFE6AD000020E508B`
- Selector is clean at candidate HEAD. Root copy is dirty with unknown owner; do not use root selector.
- No T16 test overlap identified: T16 prepared `test_worktree_release_forwards_worktree_id` and `test_worktree_cleanup_requires_registered_worktree_id`; neither changes this selector.

## Exact selector, pending T20 GO

Run once from the candidate checkout only:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_verification.py
```

Do not run until T20 issues a fresh one-shot GO and pre-run hashes still match. No test run in this handoff.

## Prior focused receipts

- `tests/test_agent_receipt_completion_t09.py`: candidate 15 passed in 2.51s; root 15 passed in 4.93s. Existing receipts are in `t09-root-integration-receipt-20261004-r6.json`; do not repeat those selectors.
- This next selector covers missing receipts, verifier/storage errors, stale revision, and mutation-generation mismatch.

## Remaining master-plan acceptance

Still needs owned evidence or owner handoff for: benchmark/source-review evidence kinds; shared work-orchestrator gate; owned worktree identity/TTL and safe cleanup; cancelled task, spoofed pass, foreign worktree, and dirty cleanup cases. Focused receipt pass does not close T09 or release acceptance.

## Lease and integration boundary

Local AI Hub coordination was not queried per user instruction. Codex app artifact list contained no `t09-root-current` attachment; no native coordination lease receipt is available. Record lease state as unverified. No root/master edits or integration authorized by this handoff.
## T20 one-shot GO result

- Pre-run and post-run identity matched: HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; source SHA-256 `A1EF1BBB5BCAEC37CB7AFB9B3088C7C5EB116DE5166A0C7B4E9806DAD8C6F71D`; selector SHA-256 `044557FCCB5B244E8F4631F648A354CB6CD0367738BBF90CFE6AD000020E508B`.
- Exact command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_verification.py`
- Result: exit 0, **21 passed in 2.42s**. One run; no retry or other selector.
## Candidate-only cancelled-receipt regression

- Added `test_cancelled_task_with_valid_receipt_cannot_complete` to the T09-owned receipt test module.
- Preimage selector SHA-256: `907C744B657376D7FB797A97F8ECCD5493740AF11449BAA9F220C674B9D9AA48`.
- Postimage selector SHA-256: `68F44C4DC5B1023827E17F2CFCB842A44581C2C6D3E26305C8618EDDF9AC2528`.
- Production source `src/local_ai_hub/agent_tasks.py` unchanged: SHA-256 `73A5BDBB25205B1F789A6E452D3B28AC24A278D781D071AC6FABE347992BDCBB`; candidate HEAD unchanged `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Exact command from candidate CWD: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_receipt_completion_t09.py::test_cancelled_task_with_valid_receipt_cannot_complete`
- Result: exit 0, **1 passed in 0.48s**. Candidate only; no root selector or integration.- Root file remained unchanged at integration preimage SHA-256 `D34BA6EF2B4B8F695368C6025D5BCC0745385F8F6DD4492F8FBE4C482B5A11B1`, blob `8f5f0438233553e998cc9fa4225fb55f41537d6e`; root HEAD remains `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Integration not performed.
## Candidate-only retrieval-index recovery regression

- Added `test_keyword_search_backfills_missing_index_after_reopen` to the same T09-owned test module. Deletes only the temporary test DB search-index tables, then verifies fresh `TaskStore` rebuilds from durable task projection.
- Test-module preimage SHA-256: `68F44C4DC5B1023827E17F2CFCB842A44581C2C6D3E26305C8618EDDF9AC2528`.
- Test-module postimage SHA-256: `13ACC8FA17B1511D3A31898D5142A6563FB8EDBFAB3829FB05EEBA031CBE291E`.
- Production `agent_tasks.py` unchanged in candidate: `73A5BDBB25205B1F789A6E452D3B28AC24A278D781D071AC6FABE347992BDCBB`.
- Exact candidate command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_receipt_completion_t09.py::test_keyword_search_backfills_missing_index_after_reopen`
- Result: exit 0, **1 passed in 0.38s**. One run.
- Root remains untouched at HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; root selector SHA-256 `D34BA6EF2B4B8F695368C6025D5BCC0745385F8F6DD4492F8FBE4C482B5A11B1`; root `agent_tasks.py` SHA-256 `5CE57D0EF0B7A17992F604AB67390E481702B0F51393C375102623475FCF280A`.
## Receipt evidence-kind acceptance

- Added durable documentation completion without `command_id`, plus model-assessment rejection for a test criterion, in `tests/test_agent_receipt_completion_t09.py`.
- Test module first image before this addition: `13ACC8FA17B1511D3A31898D5142A6563FB8EDBFAB3829FB05EEBA031CBE291E`. Current postimage SHA-256: `39AEDECF0238D40ED94AD5EF1757FD12E47915F5534AD0B54D7981A758142CD4`.
- Production `agent_verification.py` unchanged: SHA-256 `A1EF1BBB5BCAEC37CB7AFB9B3088C7C5EB116DE5166A0C7B4E9806DAD8C6F71D`.
- First combined run had an invalid source-review fixture: exit 1, `1 failed, 1 passed`; `record()` correctly required proof kind `work_source_review` and matching criterion list. Corrected fixture only; no production change.
- Corrected source-review E2E selector: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_receipt_completion_t09.py::test_source_review_receipt_without_command_completes_documentation_task` — exit 0, **1 passed in 0.51s**.
- In the first combined run, `test_model_assessment_artifact_cannot_satisfy_test_receipt` passed: invalid model artifact rejected by `record()` as trusted test evidence.
- Root/test source was not edited; no root tests or integration.- Final combined rerun after fixture correction, selector-file SHA-256 `39AEDECF0238D40ED94AD5EF1757FD12E47915F5534AD0B54D7981A758142CD4`: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_receipt_completion_t09.py::test_source_review_receipt_without_command_completes_documentation_task tests/test_agent_receipt_completion_t09.py::test_model_assessment_artifact_cannot_satisfy_test_receipt` — exit 0, **2 passed in 0.78s**.
## Benchmark evidence-type regression

- Added `test_passed_benchmark_receipt_requires_command_id`; infers benchmark from criterion and rejects a passed receipt with evidence but no execution command.
- Test-module preimage SHA-256 `39AEDECF0238D40ED94AD5EF1757FD12E47915F5534AD0B54D7981A758142CD4`; postimage SHA-256 `3018B29468928EC6323E2546EF195DA0DA0B8E5D19AFC61FC569A6C51A8FC7DD`.
- Exact candidate selector: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_receipt_completion_t09.py::test_passed_benchmark_receipt_requires_command_id` — exit 0, **1 passed in 0.21s**.
- Production source unchanged: `agent_verification.py` SHA-256 `A1EF1BBB5BCAEC37CB7AFB9B3088C7C5EB116DE5166A0C7B4E9806DAD8C6F71D`. No root edit.
## Full T09 candidate selector after acceptance additions

- Exact command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_receipt_completion_t09.py`
- Result: exit 0, **20 passed in 5.92s**.
- Pre/post identity unchanged: candidate HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; test SHA-256 `3018B29468928EC6323E2546EF195DA0DA0B8E5D19AFC61FC569A6C51A8FC7DD`; `agent_tasks.py` SHA-256 `73A5BDBB25205B1F789A6E452D3B28AC24A278D781D071AC6FABE347992BDCBB`; `agent_verification.py` SHA-256 `A1EF1BBB5BCAEC37CB7AFB9B3088C7C5EB116DE5166A0C7B4E9806DAD8C6F71D`.
- Root unchanged: HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; receipt test SHA-256 `D34BA6EF2B4B8F695368C6025D5BCC0745385F8F6DD4492F8FBE4C482B5A11B1`; `agent_tasks.py` SHA-256 `5CE57D0EF0B7A17992F604AB67390E481702B0F51393C375102623475FCF280A`.