# T05 root-current integration packet receipt — 2026-10-04

Status: **review-only comparison packet; do not apply wholesale**. Root checkout was not written and no tests were rerun for packet creation.

## Packet pins

- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- T05 candidate HEAD: `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`.
- Merge base: `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- Comparison patch: `artifacts/handoff/t05-root-current-four-file-comparison-20261004-v2.patch`.
- Patch SHA256: `FBCAA00F767B5171383F0696FE2B4A60AB1D489E0C3AFEE19EEA8B7EA51AEEE1`.
- `git apply --stat`: parsed **4 paths**, 1,898 insertions, 681 deletions.
- `git apply --check --whitespace=error` against root current: **PASS**, exit 0. This is a textual preimage check only; it does not make the comparison semantically safe to apply.
- An initial v1 artifact was malformed (`git apply --stat` rejected EOF); v2 above is the valid immutable packet. V1 remains untouched for audit.

## Root/candidate file pins and conflict map

| Path | Root base blob | Root current SHA256 / state | Candidate HEAD blob | Candidate current SHA256 | Root dirty hunk assessment |
|---|---|---|---|---|---|
| `src/local_ai_hub/agent_memory.py` | `c53e05b814e46bbac63b2f65aa87fab5d29fbca0` | `50A101E9C92C5FED942AB86494ACE9B87A68FC92D1D2E7EFBD67509D57AC85E4` / modified | `4e6fb2fdbf829c188ebc73081c88e85b90482f6f` | `71FFF0070772E7CBC31882E27B56DDC6280C32C5672AD1C0EA516AA6F18B56A5` | **Semantic conflict / superseded.** Root current already has `_memory_deletion_event`, strict transactional delete event append, identity predicates, and replay rejection. Candidate’s source replacement is older/weaker; candidate replay returns a record while root intentionally raises `ValueError`. Do not transplant source wholesale. |
| `tests/test_agent_memory.py` | `c96309b1a4b57eec3f360faa51493e90234f87ec` | `5419B7C8718A2C3D2C5A082C59FA6A050DA2C6881BF2EC3EB2147F6347B0B74F` / modified | `c96309b1a4b57eec3f360faa51493e90234f87ec` | `A523E4E5FA22E37DA49321F60BF0D62C2C468556D3E2D3D0D69AC59F79E98ACE` | **Dirty-hunk overlap.** Candidate corrects stale identity assertions and adds regressions; full file comparison also contains many other changes. The 13 focused identity hunk set is narrower than this whole-file patch. Prior isolated test patch SHA `A10AD4F7B682F2E2EFD19EA6745A926101512932EB9CA50A809AE38171358A58` is separate evidence, not this packet. |
| `tests/test_agent_memory_http_identity.py` | absent from root HEAD | `08838FC89DA0B238DAABDEC304E5728EA70D394D5B9B0A49CC9ABA3878251A6A` / untracked | absent from candidate HEAD | `B810DE282D89363A1C7C967E190A7F8EC82518EE0DBFFE3181CC875524BC9AC3` | **Untracked-file overlap.** Root and candidate both have their own dirty file. Identity-denial proof hunks can be isolated, but new replay test assumes candidate’s non-raising replay contract and conflicts with root source behavior. |
| `tests/test_t05_memory_delete_artifacts.py` | absent from root HEAD | `4F79E0C19498706AB351E8EC4F9CA617E95592EA9B351269DC87710B4FF22940` / untracked | absent from candidate HEAD | `4054ECCCB63C0261F2A608A52058922BC13F8FE0FD86321285FC6715F394AB77` | **Untracked-file overlap.** Root and candidate versions differ. The candidate’s replay test expects `record()` to return after deletion; root-current source rejects that replay. Keep this test hunk out of an apply-ready patch until the contract is reconciled. |

The comparison patch contains only these four paths. The existing broader T05 manifest is excluded; this separate receipt carries the integration pins and explains why the patch is comparison-only. No `/api/context/pack`, T08-owned path, or root file is included.

## Test receipts already run

- Root historical suite: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_memory.py tests/test_agent_memory_http_identity.py` — **29 passed, 13 failed in 30.28s**. No root rerun.
- Candidate identity batch, exact command — **12 passed in 8.04s**. It included adjacent `test_mark_stale_for_revision_preserves_metadata_and_emits_event`; actual missing root-failure selector ran separately below.

  ```powershell
  python -B artifacts/handoff/t05-root-provider-pytest.py -q -p no:cacheprovider --tb=short tests/test_agent_memory.py::test_find_filters_global_and_repository_rows_by_tenant_and_root tests/test_agent_memory.py::test_legacy_unscoped_lookup_rejects_nonempty_task_and_session_context tests/test_agent_memory.py::test_memory_find_enforces_root_repository_and_tenant_identity tests/test_agent_memory.py::test_global_promotion_requires_user_approval tests/test_agent_memory.py::test_global_promotion_succeeds_with_user_approval tests/test_agent_memory.py::test_evidence_memory_persists_revision_metadata_and_is_idempotent tests/test_agent_memory.py::test_repository_revision_is_preserved_in_provenance tests/test_agent_memory.py::test_mark_stale_for_revision_preserves_metadata_and_emits_event tests/test_agent_memory.py::test_mark_stale_for_revision_matches_relative_and_absolute_roots tests/test_agent_memory.py::test_mark_stale_for_revision_deduplicates_and_caps_changed_paths tests/test_agent_memory.py::test_mark_stale_batch_rolls_back_and_repeats_idempotently tests/test_agent_memory_http_identity.py::test_http_memory_get_and_mutations_bind_transport_tenant_and_project_identity
  ```

- Missing identity regression, exact command — **1 passed in 4.96s**:
  `python -B artifacts/handoff/t05-root-provider-pytest.py -q -p no:cacheprovider --tb=short tests/test_agent_memory.py::test_mark_stale_for_revision_matches_beyond_100k_rows`.
- Candidate delete/FTS command: `python -B artifacts/handoff/t05-root-provider-pytest.py -q -p no:cacheprovider --tb=short tests/test_t05_memory_delete_artifacts.py::test_scoped_delete_purges_fts_and_embedding_artifacts tests/test_t05_memory_delete_artifacts.py::test_delete_cleanup_failure_rolls_back_memory_and_search_state tests/test_t05_memory_delete_artifacts.py::test_replaying_record_after_delete_does_not_restore_memory_or_fts` — **5 passed in 3.15s**.
- Candidate HTTP replay, exact command — **1 passed in 4.59s**:
  `python -B artifacts/handoff/t05-root-provider-pytest.py -q -p no:cacheprovider --tb=short tests/test_agent_memory_http_identity.py::test_http_unscoped_global_delete_then_record_replay_keeps_tombstone`.
- Earlier candidate focused identity command — **5 passed in 4.96s**:
  `python -B artifacts/handoff/t05-root-provider-pytest.py -q --tb=short -p no:cacheprovider tests/test_agent_memory.py::test_scoped_memory_delete_still_enforces_tenant tests/test_agent_memory.py::test_find_for_context_session_memory_requires_session_and_tenant tests/test_agent_memory.py::test_find_for_context_task_memory_requires_root_task_and_tenant tests/test_agent_memory.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope tests/test_agent_memory_http_identity.py::test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope`.
- Earlier pre-fix three-selector candidate run — **1 passed, 2 failed in 5.03s**; both failures hit the tuple/string-index bug fixed afterward. The later HTTP replay test and delete/FTS suite passed after that fix.
- These are candidate receipts only. No test was run against root during this packet preparation.
