# T08 task memory adoption acceptance — 2026-10-01

## Candidate verification

- Candidate HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- Exact command: `$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_task_memory_adoption.py tests/test_agent_incident_scope.py tests/test_agent_state_e2e.py::test_local_app_wires_scoped_memory_adoption_on_create_and_resume tests/test_agent_tasks.py::test_same_status_retry_serializes_with_concurrent_transition_event`
- Result: **16 passed in 8.50s**, exit 0. All fixtures use their own `tmp_path`; app E2E asserts `TaskStore` and `MemoryStore` share the same `AgentStateStore`.
- The app E2E creates/resumes a task, checks attached context and checkpoint audit, completes the task, records user-confirmed memory, then confirms the next task receives it.
- During test authoring, a too-narrow exact-ID assertion failed once: `ContextCompiler` returns all matching scoped records, so the corrected expectation includes the three active/confirmed same-root/tenant memories. Updated selector passed in the final 16-test run.

## Acceptance matrix

| Area | Evidence | Result |
|---|---|---|
| Scope/privacy | `test_create_uses_only_matching_root_and_tenant_without_saving_prompt_memory`; `test_create_and_resume_attach_only_scoped_negative_knowledge` | root/tenant scoped retrieval; tenantless GLOBAL usable; other root/tenant, legacy unscoped incident, sensitive and candidate memory excluded; task prompt not saved |
| Fail-open | `test_empty_lookup_is_silent_and_unavailable_lookup_fails_open`; `test_corrupt_record_and_deadline_fail_open_with_warning`; `test_stale_and_expired_memory_are_skipped_with_bounded_warnings` | empty lookup silent; unavailable/corrupt/deadline fail open with bounded warnings; stale/expired skipped |
| Budget | `test_lookup_bundle_respects_item_and_token_caps` | at most 5 items and 512 estimated tokens |
| Lifecycle/audit | `test_resume_refreshes_memory_and_checkpoint_keeps_audit_bundle`; `test_volatile_memory_requires_checkpoint_source_check_and_bundle_survives_checkpoint`; app E2E | resume refreshes, checkpoint keeps context/audit; used IDs or textual skip reason required; volatile use needs current-source check |
| Provenance | `test_correction_stale_transition_and_delete_preserve_provenance_lineage`; `tests/test_agent_incident_scope.py` | tenant/root provenance preserved across correction/stale/delete; incident scope isolation covered |
| Post-task learning | app E2E selector | after completion, confirmed memory appears in next task context through the app's existing shared store |
| HTTP persisted receipt | T09 receipt | reported passed by parent task; not rerun here |
| Coordination consumer | `tests/test_t08_coordination_identity.py` | trusted same-tenant repository share; legacy root-only and unrelated IDs excluded; TASK/WORKTREE/BRANCH local; stale invalidation stays on physical root; forged HTTP ID ignored |

T21 owns the opaque `ProjectContext.coordination_id`; T08 consumes it without changing the physical root or creating another identity layer. Candidate configuration module is not yet T21-integrated, so the HTTP consumer test injects a trusted ProjectContext at the server resolver seam.

## Coordination consumer verification

- Exact command: `$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t08_coordination_identity.py tests/test_agent_task_memory_adoption.py tests/test_agent_incident_scope.py tests/test_agent_state_e2e.py::test_local_app_wires_scoped_memory_adoption_on_create_and_resume tests/test_agent_tasks.py::test_same_status_retry_serializes_with_concurrent_transition_event`
- Result: **23 passed in 15.21s**, exit 0.
- Initial RED: `find_for_context(..., coordination_id=...)` raised `TypeError` because the candidate API lacked the trusted scope argument. Consumer test suite then passed after implementation.
- HTTP integration uses a real `LocalAIApp`/HTTP server and competing IDs: the server-resolved ID returns its matching record; client-forged context and memory-find IDs do not, and a source-root-less repository delete is denied.
- Repository writes bind `provenance.repository_id` from server ProjectContext; repository deletion requires matching source root plus authenticated tenant.
- Cross-worktree retrieval retains each record's source `scope_id` and `provenance.root`; source freshness and mutations continue to use the physical root.
- Root tests and integration were not run; T20 owns the root-current merge and slots. The new consumer sources live only in the T08 candidate worktree.

## Root-current handoff

- T08 patch: `t08-memory-adoption-root-current-matrix-20261001.patch`; SHA-256 `44FB9D93814373EA587622D20D11F856A6D039DE74056E00B103164F8EE428D8`.
- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root preimages: `tests/test_agent_tasks.py` `690AE3495E4249ABEB53CD7A51DB1914341E2E719DE63C90E22BF3704B9FB504`; `tests/test_agent_state_e2e.py` `152E7FA69B3CEBD42F01539FBB71D88F776FFD6C479D8742756A2A34695A6390`.
- T08 `git apply --check`: passed; source/test AST parse passed; no root write/test performed here.
- The root adoption test still calls scoped delete without identity. Apply the separate T05-owned fix first/alongside: `t05-root-current-scoped-delete-t08-test-fix.patch`, SHA-256 `DA983C68832E4BCDBB2708449242E85CA315AE4C84E8E029EA03561F6A5375EC`. Sequential scratch apply T08 then T05 passed.
- T20 owns root integration and root test scheduling. Root acceptance remains not run.
