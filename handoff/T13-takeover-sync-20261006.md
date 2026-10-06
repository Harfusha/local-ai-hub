# T13 lifecycle checkout synchronization, 2026-10-06

## Ownership and preservation

Only checkout `C:/Users/Adam/.codex/worktrees/t13-lifecycle-8429/.local-ai-hub` is owned by this integration. Branch: `codex/sync-t13-lifecycle-8429-20261006`. No root-checkout edits, master-ref writes, pushes, new worktrees, stash, reset, cleanup, or blind application of historical patches.

The takeover continued the existing merge of `42932634b587880da06b2b0de882f88b54805c20` into `38967ac0cea211113927bb7584cf9271a7412a48`. It was not restarted or aborted. Preserved checkpoint ref `refs/checkpoints/t13-lifecycle-sync-original-20261006` points to `708282ff64bb345a794e364b1c765521ee7bc876`, which committed the tracked dirty work. Its parent, the original checkout HEAD, is `e9d6d82e535f5d5ca87018b89b33c2665084b77b`. Commit `38967ac0` preserves all five ordinary untracked source/test/handoff files, including `tests/test_shared_runtime_security_lifecycle.py` and `tools/resolve_hub_pids.py`.

Hub had already failed terminally before takeover. User explicitly authorized native fallback with no Hub retries or polling. Exact prior Hub failure envelope was not supplied in takeover; no fresh Hub evidence is claimed. Token-economizer skill was read; its specified `ensure-tools.ps1` is absent. No tooling installation or PATH change was performed.

## Manual conflict decisions

All nine conflicted files were reviewed, including all nineteen HTTP conflict blocks. Source and tests remain preserved even where acceptance is incomplete.

- HTTP retains current master imports, route registry, admin action tokens, audit events and local mode-read allowance; configured monitor/read/write/admin grants and root/tenant binding are retained.
- Debug request capture is metadata-only. Master redacted raw request capture was not adopted because arbitrary request fields can contain private source, prompts and paths.
- Task lists retain root/tenant filtering and current master query validation/truncation reporting. Scoped task helpers and verification binding remain in place.
- Memory deletion retains master's scoped `delete` arguments, supplemented by historical bound-record checks. Promotion retains bound-record checks and server-authenticated approver classification; payload approval cannot authorize global promotion.
- Strict `include_body` accepts actual body booleans and query `true`/`false`; invalid values return HTTP 400 through the preserved guards. Duplicate helper/import conflict debris was removed.
- ContextRequest combines `scoped_task_only` with master's coordination ID, identity, settings digest and path hints. `/api/context/pack` owner remains T14; only conflict reconciliation was performed, without redesign.
- Current process ownership and safe job cleanup remain fail-closed; failing numeric-PID/group fixtures were not used to weaken them. The automatically merged supervisor lacked its required `json` import; integration restores it.
- Installation/update/MCP documentation preserves lifecycle/conversation contracts alongside current master capability, PathHint and safety qualifications. Both prompts retain the configured preprocessing-provider preservation rule. Pinned source explicitly says no Gemini provider implementation was found; this integration neither removes nor invents one. CodeGraph removal remains master-owned, with external standalone-tool documentation preserved.

## Targeted validation before final master catch-up

All pytest commands ran natively, with this agent as owner, in this checkout. They import local source and create temporary runtime/test state beneath ignored `.sync-validation-t13-*` directories; these are side-effecting targeted checks, not read-only audits. Runtime state is preserved locally and excluded from source commits. No full release suite, deployment, model inference, model download, installer or live Hub verification was run.

1. `python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=.sync-validation-t13-first tests/test_client_transport.py tests/test_delivery_policy.py tests/test_http_find_symbol_boolean.py tests/test_http_code_find_symbol_include_body.py tests/test_http_admin_action_auth_t18.py tests/test_http_user_acl.py tests/test_t13_sync_cancellation.py tests/test_t13_mode_resume_matrix.py tests/test_process_utils.py tests/test_process_utils_timeout_cleanup.py`
   - Result: **93 passed, 20 failed**, 13.22 seconds.
2. `python -B -m pytest -q --tb=line -p no:cacheprovider --basetemp=.sync-validation-t13-scoped tests/test_shared_runtime_security_lifecycle.py tests/test_agent_memory_http_identity.py tests/test_memory_delete_identity_contract.py tests/test_unified_task_context.py tests/test_unified_task_context_transport.py tests/test_task_context_task_integration.py tests/test_t19_codegraph_removal.py -k 'not test_synchronous_codegraph_timeout_reports_cleanup_error'`
   - Result: **110 passed, 21 failed, 1 skipped, 1 teardown error**, 48.64 seconds. Windows directory-symlink capability caused the skip. The selection expression excluded no known required T13 acceptance; no general release acceptance is claimed.
3. AST parsing of the six formerly conflicted Python files passed. `git diff --check` passed after conflict resolution.

## Outstanding acceptance issues

- Delivery-policy unit handlers omit `headers`; three async delivery tests fail before submission. Historical body `request_id` documentation and newer HTTP-header handling need owner review.
- Current master user ACL tests expect per-user/supervisor credentials and `_required_permission`/`_authenticated_tenant`; preserved implementation does not fulfill that contract. Admin mode test mocks module functions while current route resolves `_operational_mode_api`; mode control acceptance remains incomplete.
- Legacy process tests assume numeric group signaling or fake process cleanup that current stable-ownership safety intentionally refuses. Cancellation/drain acceptance remains incomplete; do not restore unsafe signaling to satisfy fixtures.
- Shared runtime security tests include principal-as-actor expectations incompatible with master's audit actor classification, readiness/ownership fixtures, verification/event fixtures and async trace field-count expectations. Missing supervisor `json` import was fixed after the reported run; follow-up results below will identify actual remaining failures.
- Global/unscoped memory tests conflict with preserved root authorization and scoped mutation restrictions. No broadening of memory access was made to satisfy them.
- `test_context_endpoint_composes_agent_and_repository_context` receives HTTP 404; T14 must review that transport contract.
- CodeGraph removal tests reject explanatory `codegraph` text in generator documentation and expect older standalone wording. This does not establish a reintroduced runtime backend. One teardown reports an unclosed socket through `PytestUnraisableExceptionWarning`.

These failures are committed unfinished work, not successful runtime acceptance. Historical receipts and owner patches remain historical. Final master snapshot, changed-file manifest and verification are appended below after catch-up.

## Final catch-up and fresh verification

The unresolved takeover merge was committed as `a088fc82de6fefa27c604e653eb01aa60c7a1fe3`, with parents `38967ac0` and `42932634`. Master advanced concurrently. Catch-up to `4891878b7cd887132cfaa8fc3d26f0bca3840702` was committed as `d84141e976818606f989c45bc31d192ac41fb38a`; its only conflict was `.gitignore`, resolved by retaining both owners' runtime exclusions. The next master snapshot is `25580e005da0442f73530787196d09e7eab57ff2`. This final merge auto-combined `async_jobs.py` without conflicts; its remaining difference from that master is the preserved metadata-only debug capture and exclusion of raw observer/error payloads. Master's newer async scheduling/admission source remains integrated.

The older master-owned `handoff/T13-sync-integration-20261006.md` describes another checkout. A Windows case-insensitive filename collision temporarily put this note's text there; that older note was restored to its committed content before catch-up and remains preserved. This takeover note has a distinct filename. No historical integration note was replaced in the committed result.

Fresh checks after the supervisor import/documentation changes:

- `python -B -m pytest -q --tb=line -p no:cacheprovider --basetemp=.sync-validation-t13-final-contracts tests/test_client_transport.py tests/test_http_find_symbol_boolean.py tests/test_http_code_find_symbol_include_body.py tests/test_t13_sync_cancellation.py tests/test_t13_mode_resume_matrix.py tests/test_unified_task_context.py tests/test_task_context_task_integration.py tests/test_delivery_policy.py -k 'not test_async_delivery_maps_reason_payload_to_the_existing_job_contract and not test_async_delivery_maps_review_diff_to_durable_review_job and not test_cold_start_review_diff_auto_delivery_is_async'`: **61 passed, 3 deselected**, 7.44 seconds. The three excluded failures remain explicitly open above.
- `python -B -m pytest -q --tb=line -p no:cacheprovider --basetemp=.sync-validation-t13-final-supervisor tests/test_shared_runtime_security_lifecycle.py -k 'test_supervisor_lock_records_and_releases_exact_process_owner or test_supervisor_recovers_expired_lock_and_preserves_current_owner or test_supervisor_lock_does_not_reclaim_foreign_or_unknown_owner or test_concurrent_stale_lock_reclaim_has_exactly_one_supervisor or test_crashed_supervisor_releases_os_guard_and_next_process_reclaims_owner or test_supervisor_restart_gracefully_reaps_owned_hub_before_respawn'`: **6 passed, 106 deselected**, 7.03 seconds. These six formerly failing supervisor cases now pass; readiness and other cases were not reverified by this selection.

Fresh checks with final `25580e00` master source merged:

- `python -B -m pytest -q --tb=line -p no:cacheprovider --basetemp=.sync-validation-t13-master-async tests/test_async_jobs.py tests/test_async_job_reliability_contract.py tests/test_t13_sync_cancellation.py tests/test_t13_mode_resume_matrix.py`: **43 passed, 6 failed**, 7.11 seconds. Failures remain: raw trace request assertion (`KeyError: 'task'`), both request-ID retry cases, legacy running-job replay, queued dispatch-not-before persistence, and restart dispatch-not-before persistence. Raw request capture is intentionally not restored. Remaining retry/recovery/scheduling expectations need owner reconciliation; successful runtime acceptance is not claimed.
- All **18 master-relative changed Python files parse successfully** using `ast.parse` in memory. No compileall, build or generated bytecode was requested.
- `git diff --check 25580e00 -- src tests tools docs .gitignore handoff/T13-takeover-sync-20261006.md`: passed.
- `git diff --quiet 25580e00 -- src/local_ai_hub/preprocess.py src/local_ai_hub/repo_scan.py tools/setup.py tools/uninstall.py`: returned 0. Preprocessing and setup/uninstall source were not replaced with historical versions. Configured provider preservation and CodeGraph removal remain intact; no Gemini runtime/provider execution is proved.
- The earlier broad `git diff --cached --check` against the old checkpoint did **not** pass: incoming master includes historical handoff-overlay whitespace/CRLF warnings. These were retained without unrelated formatting. The final master-relative integration whitespace check above passed.

Final acceptance is **COMMITTED INTEGRATION, RUNTIME PARTIAL**. Test sets overlap; their counts must not be added into a unique-test total. Earlier failures remain open unless explicitly covered by the passing follow-up selections. No full release suite or installed-runtime acceptance.

## Changed paths versus final master snapshot

Reference: `25580e005da0442f73530787196d09e7eab57ff2`. Exactly 25 paths differ:

```text
M .gitignore
M docs/INSTALL_PROMPT.md
M docs/MCP_AND_AGENTS.md
M docs/UPDATE_PROMPT.md
A handoff/T13-takeover-sync-20261006.md
A handoff/t13-find-symbol-include-body-handoff.md
A handoff/t13-find-symbol-include-body.patch
M src/local_ai_hub/agent_context.py
M src/local_ai_hub/async_jobs.py
M src/local_ai_hub/client.py
M src/local_ai_hub/config.py
M src/local_ai_hub/http_server.py
M src/local_ai_hub/mcp_server.py
M src/local_ai_hub/process_utils.py
M src/local_ai_hub/supervisor.py
M src/local_ai_hub/task_context.py
M tests/test_client_transport.py
M tests/test_config_hardware.py
M tests/test_conversation_continue_route_contract.py
M tests/test_delivery_policy.py
A tests/test_http_code_find_symbol_include_body.py
A tests/test_shared_runtime_security_lifecycle.py
M tests/test_surface_and_packaging.py
A tools/resolve_hub_pids.py
M tools/service.py
```

All original dirty code/tests/docs are reachable through the checkpoint and merge parents. Five preserved ordinary untracked files are committed. Other artifacts and validation state stay preserved locally; `.sync-validation-t13-*` directories are ignored and excluded from commits. Final merge is on the existing sync branch; master is only read and merged as a parent. Post-commit ancestry, unresolved-index and clean-source checks are reported in the final chat handoff.
