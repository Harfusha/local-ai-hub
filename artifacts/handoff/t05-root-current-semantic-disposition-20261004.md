# T05 root-current semantic disposition — 2026-10-04

## Scope and immutable comparison

T05 candidate HEAD: `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`  
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`  
Merge base: `2b33602adef0d030fea66cdcc04ca742c60b2e32`

Comparison-only patch: `artifacts/handoff/t05-root-current-four-file-comparison-20261004-v2.patch`  
SHA-256: `FBCAA00F767B5171383F0696FE2B4A60AB1D489E0C3AFEE19EEA8B7EA51AEEE1`  
Parser/check receipt: four paths, 1,898 insertions / 681 deletions; `git apply --check --whitespace=error` succeeded against root current. This is textual applicability only. Patch was not applied.

## Per-path pins

| Path | Root base blob | Root current SHA-256 | Candidate current SHA-256 | Root status |
|---|---|---|---|---|
| `src/local_ai_hub/agent_memory.py` | `c53e05b814e46bbac63b2f65aa87fab5d29fbca0` | `50A101E9C92C5FED942AB86494ACE9B87A68FC92D1D2E7EFBD67509D57AC85E4` | `71FFF0070772E7CBC31882E27B56DDC6280C32C5672AD1C0EA516AA6F18B56A5` | modified |
| `tests/test_agent_memory.py` | `c96309b1a4b57eec3f360faa51493e90234f87ec` | `5419B7C8718A2C3D2C5A082C59FA6A050DA2C6881BF2EC3EB2147F6347B0B74F` | `A523E4E5FA22E37DA49321F60BF0D62C2C468556D3E2D3D0D69AC59F79E98ACE` | modified |
| `tests/test_agent_memory_http_identity.py` | absent | `08838FC89DA0B238DAABDEC304E5728EA70D394D5B9B0A49CC9ABA3878251A6A` | `B810DE282D89363A1C7C967E190A7F8EC82518EE0DBFFE3181CC875524BC9AC3` | untracked |
| `tests/test_t05_memory_delete_artifacts.py` | absent | `4F79E0C19498706AB351E8EC4F9CA617E95592EA9B351269DC87710B4FF22940` | `4054ECCCB63C0261F2A608A52058922BC13F8FE0FD86321285FC6715F394AB77` | untracked |

## Symbol map and disposition

- `_memory_deletion_event`, `MemoryStore.delete`, `_record_event_and_save`: root already rejects resurrection. Delete appends a strict tombstone before projection deletion in the caller-owned transaction, validates append, rolls back on failure, then publishes after commit. Replay rejects tombstoned records, including a changed idempotency key.
- Candidate delete removes projection first, appends non-strictly without validating the append result, and has narrower identity checks. Candidate replay tests expect a returned record while leaving projection absent. Those semantics are weaker or conflict with root-current behavior. No source hunk warranted.
- Candidate-specific tuple row indexing fix is not a root gap.
- Root's identity/scope find, promotion, and stale-revision handling are covered by the targeted selector results below. No isolated missing behavior identified.
- Do not apply the four-file patch wholesale. Its replay assertions need contract reconciliation before any test-only transplant.
- T08 owner confirmed caller-owned open transaction for append and post-commit-only publication; T05 source stayed outside T08 scope.
- T09 owner confirmed no shared-memory identity/scope/delete/tombstone/replay ownership. T09 scope is receipt persistence/gating and structured task descriptions plus keyword search/index; no T05 acceptance dependency identified.

## Post-release candidate selectors

T08 completed and released its shared test slot. Existing root 29-pass suite was not rerun. Exact candidate command, via the T05 root-provider wrapper:

`python -B artifacts/handoff/t05-root-provider-pytest.py -q -p no:cacheprovider --tb=short tests/test_agent_memory.py::test_find_filters_global_and_repository_rows_by_tenant_and_root tests/test_agent_memory.py::test_legacy_unscoped_lookup_rejects_nonempty_task_and_session_context tests/test_agent_memory.py::test_memory_find_enforces_root_repository_and_tenant_identity tests/test_agent_memory.py::test_global_promotion_requires_user_approval tests/test_agent_memory.py::test_global_promotion_succeeds_with_user_approval tests/test_agent_memory.py::test_evidence_memory_persists_revision_metadata_and_is_idempotent tests/test_agent_memory.py::test_repository_revision_is_preserved_in_provenance tests/test_agent_memory.py::test_mark_stale_for_revision_preserves_metadata_and_emits_event tests/test_agent_memory.py::test_mark_stale_for_revision_matches_relative_and_absolute_roots tests/test_agent_memory.py::test_mark_stale_for_revision_deduplicates_and_caps_changed_paths tests/test_agent_memory.py::test_mark_stale_batch_rolls_back_and_repeats_idempotently tests/test_agent_memory_http_identity.py::test_http_memory_get_and_mutations_bind_transport_tenant_and_project_identity tests/test_agent_memory.py::test_mark_stale_for_revision_matches_beyond_100k_rows tests/test_t05_memory_delete_artifacts.py::test_scoped_delete_purges_fts_and_embedding_artifacts tests/test_t05_memory_delete_artifacts.py::test_delete_cleanup_failure_rolls_back_memory_and_search_state tests/test_t05_memory_delete_artifacts.py::test_replaying_record_after_delete_does_not_restore_memory_or_fts tests/test_agent_memory_http_identity.py::test_http_unscoped_global_delete_then_record_replay_keeps_tombstone`

Result: **19 passed in 12.62s**, exit 0. Command broker returned `terminal=true`, `retryable=false`, `mutation_worktree_required=true`; one bounded native fallback ran after release. Post-run four candidate hashes and dirty status matched the pre-run pins. Root remained untouched.

## Final integration choice

Review packet only. No source or test patch to apply to root: current source already has stronger delete/replay behavior, and candidate replay expectations conflict with it. Preserve all candidate changes and inherited dirty paths. The T05 manifest remains excluded.

