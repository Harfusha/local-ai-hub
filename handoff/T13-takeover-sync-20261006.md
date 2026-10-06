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
