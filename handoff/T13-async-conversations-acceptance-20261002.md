# T13 async jobs and conversations — acceptance handoff

Date: 2026-10-02 (Europe/Prague)

## Scope and workspace

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`
- Candidate `HEAD`: `6050c41ce5510a6de3eaeb674a180560ea404f24`
- Scope: durable async jobs, conversation delivery/cancellation, and T13-owned running-job behavior across restricted modes and resource release.
- Preserve all existing dirty files. No root checkout edits. `/api/context/pack` remains Agent 2 ownership.
- This handoff adds no implementation changes and runs no tests. T20 serial test slot remains the execution gate.

## Static review result

- `AsyncJobManager.submit` rejects `conversation=true` before persistence or dispatch with terminal, non-retryable result. Conversation continuation stays on the synchronous route.
- Mode admission serializes mode persistence, queue insertion, and executor admission. Restricted-mode cancellation sets `cancel_requested`; running jobs remain nonterminal until the executor exits.
- Active resource release blocks new inference admission, defers queued jobs, and redispatches them after the final release token ends.
- Gaming conversation release signals cancellation and waits for worker exit before model unload. A drain timeout reports active inference and prevents unload.
- Current source and test files are already dirty in this worktree. This pass preserved them without edits.

## Worktree pins

SHA-256 pins for files reviewed on 2026-10-02:

| Path | SHA-256 |
| --- | --- |
| `src/local_ai_hub/async_jobs.py` | `F564E9047A8F6FE6417D803727C77F5B98E7E9DD090EA99B58DB787DF57F92C8` |
| `src/local_ai_hub/http_server.py` | `CD384F1E28B9FCE65251C6A93E2F652382A5D606323D026F1A64DEB966860A41` |
| `src/local_ai_hub/services.py` | `609CD8352AC3DCD4E1CB2E5199392F99967EA444CFBD0711210C6424A7A9FC10` |
| `tests/test_async_jobs.py` | `B65D108A9A72C42D951B4961895AC497D1E40BDCA8D5A77A1C6E64914163912E` |
| `tests/test_conversation_continue_route_contract.py` | `D2D2D7F08EF19022E34B09B2E91D673D9176678DECB5FB57BB16036A65B66C03` |
| `tests/test_t13_gaming_conversation_release_receipt.py` | `B02800EBC6E45E2E26BE550B977CC2F296F3A1A2F85C7B4AD30D44DB334A7ECC` |

## Focused acceptance command

Run only after T20 gives serial GO. Route through `local_ai_command` first. Use native execution only after a `terminal=true`, `retryable=false` broker result.

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_async_jobs.py::test_async_job_submit_rejects_conversation_payload_before_dispatch `
  tests/test_async_jobs.py::test_dispatch_defers_queued_job_until_owned_resource_release_finishes `
  tests/test_async_jobs.py::test_dispatch_requeues_claimed_job_when_release_starts_before_admission `
  tests/test_async_jobs.py::test_gaming_rejects_new_inference_before_persistence_and_preserves_result_receipt `
  tests/test_async_jobs.py::test_maintenance_blocks_speculative_lint_before_persistence `
  tests/test_async_jobs.py::test_gaming_allows_non_inference_lint_job `
  tests/test_async_jobs.py::test_persisted_modes_gate_async_admission_without_test_overrides `
  tests/test_async_jobs.py::test_submit_before_restricted_mode_is_cancelled_at_dispatch `
  tests/test_async_jobs.py::test_submit_mode_gate_and_queue_insert_are_atomic_with_mode_transition `
  tests/test_async_jobs.py::test_restricted_mode_requests_running_job_cancellation_without_early_completion `
  tests/test_async_jobs.py::test_mode_change_receipt_reports_running_inference_until_cancel_finishes `
  tests/test_async_jobs.py::test_mode_commit_at_executor_boundary_prevents_inference_start `
  tests/test_conversation_continue_route_contract.py::test_hub_client_continues_through_production_route_and_preserves_transcript `
  tests/test_conversation_continue_route_contract.py::test_expired_conversation_is_terminal_through_production_route `
  tests/test_conversation_continue_route_contract.py::test_competing_continuation_is_retryable_in_progress_through_production_route `
  tests/test_conversation_continue_route_contract.py::test_http_async_job_submit_rejects_conversation_payload `
  tests/test_conversation_continue_route_contract.py::test_gaming_cancels_active_conversation_before_unload `
  tests/test_conversation_continue_route_contract.py::test_gaming_skips_unload_when_conversation_ignores_cancellation `
  tests/test_t13_gaming_conversation_release_receipt.py::test_gaming_release_receipt_includes_conversation_cancelled_before_snapshot
```

## Existing receipts and remaining acceptance

- The 2026-10-01 candidate manifest records a focused T13 result of 14 passed in 6.71 seconds, plus historical one-test passes for async conversation rejection and conversation-release receipt. These are historical, not fresh receipts for this pinned worktree state.
- No tests or runtime checks ran during this continuation. No inference quality, Ollama unload, physical VRAM reclaim, or hardware behavior is claimed.
- Remaining: wait for T20 serial GO, run the focused command, attach the fresh command result and exact test count, review any failures without weakening assertions, then update this handoff.

## Shared-runtime acceptance extension — implementation gated

This extension stays in T13 scope. It excludes `/api/context/pack`. Preserve current endpoint contracts, dashboard monitoring, and operational-mode behavior.

- **Per-user HTTP auth and ACL:** map each configured credential to one principal and its allowed actions. Test missing, invalid, and valid credentials; test allowed and denied actions; keep service/supervisor credentials distinct from user credentials. Preserve current anonymous behavior only when per-user auth is not configured, and keep the configured legacy API-token path compatible.
- **Liveness and readiness:** keep `/health` as bounded process liveness, including before `APP` initialization. Add separate bounded readiness response: ready only after application initialization and required service ownership setup; return 503 with a stable reason while unready. Probe must not load models or wait on inference.
- **Owner identity:** persist PID with process creation time, executable identity, and normalized state/config directory identity. Validate all fields before lock cleanup, signal, terminate, or restart. PID reuse, executable mismatch, or state-directory mismatch must leave the process untouched.
- **Safe stop/restart:** request graceful shutdown first; wait within a fixed bound; revalidate owner identity before any forced termination; restart only the matching owned service. Preserve Windows `AtLogOn` task behavior. Verify repeated stop/start and stale-owner recovery do not affect unrelated processes.
- **Monitoring compatibility:** keep dashboard/read-only monitoring behavior available under the existing contract. Test auth policy separately for administrative actions. Keep operational-mode reads and writes unchanged except for their explicit ACL decisions.

### Ownership blocker

- Current checkout is `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`, `HEAD 6050c41ce5510a6de3eaeb674a180560ea404f24`.
- `mcp__codex_app__list_artifacts` reports attached identity `C:\Users\Adam\.codex\worktrees\t13-lifecycle\.local-ai-hub`; that path does not exist. Current candidate path exists but has no matching attached-worktree record.
- Current native status: `src/local_ai_hub/http_server.py` is modified; `src/local_ai_hub/supervisor.py`, `tools/service.py`, and `tools/service_entry.py` are clean. Do not overwrite or stage any existing changes.
- Local AI Hub returned `Transport closed` for context and status. No lease ID or current owner grant is available. Therefore no source or test files in this shared-runtime extension were edited. Reconfirm candidate attachment and obtain a lease before source edits.
- Tests for this extension are not yet authored, so no executable test command is claimed. After ownership is confirmed and T20 gives serial GO, add focused tests for credential/ACL decisions, liveness-before-init versus readiness, bounded readiness timeout, matching and mismatched owner identity, PID reuse, lock cleanup, and graceful/forced stop-restart behavior. Keep test execution behind the command broker; do not use native test fallback without explicit `terminal=true` and `retryable=false`.

## T27 staged HTTP dispatcher decomposition — gated

This extends T13 acceptance only. It does not authorize route extraction yet.

### Entry gates

- T01 delivers a complete route inventory with method, path, body fields, owner, and explicit dispositions for unknown/unavailable fields. Current T01 interim report: 223 owner labels and 38 body-field gaps; CSV integrity/sign-off remains pending.
- Owners freeze the shared dispatcher descriptor and boundary before extraction: request method/path, owner, action/cost class, read/write effect, auth scope, mode decision, body parsing/limit behavior, and response/error contract. Include idempotency/recovery ownership where a route uses it.
- T13 confirms the exact root-current preimages and scoped edit lease for each touched module. Root stays untouched during candidate work.
- No T27 extraction before all gates pass. Do not infer permission from the plan row alone.

### Route ownership boundaries

- T13 may extract only operational-mode/admin, conversation-continuation, async-job, and T13-owned readiness/auth policy routes.
- T07 owns bundle-import, recovery/idempotency, and tool-accounting POST behavior. Preserve _claim_recovery and all T07 Handler.do_POST hunks.
- T08 owns /api/agent-state/* and root-scoped reap/curate integration.
- T14 exclusively owns /api/context/pack; exclude its route and tests from T13 patches.
- T17 owns vision/transcription route/service behavior.
- T18 owns dashboard/status presentation and degraded polling. T13 may enforce the shared auth/mode boundary only.
- T04 owns client transport contracts, outside Handler dispatcher extraction.
- T01 owns inventory and API contract evidence.

### Extraction and parity acceptance

- Keep Handler.do_POST as the shared HTTP boundary for authentication, request/body parsing, admission, idempotency/recovery handoff, response serialization, and error mapping. Do not replace it wholesale.
- Extract one T13-owned route module per patch. Each patch must include exact target preimage SHA-256, minimal diff, owner map, and apply-check result. Preserve adjacent owner hunks byte-for-byte.
- For every moved route, add exact old/new parity tests for method/path, auth scope, mode decision, status, headers, response shape, body validation, side effects, and error mapping. Add idempotency parity where applicable.
- Test cheap deterministic local reads/listing as allowed in gaming mode; test heavy inference/repo work, mutation, and administration as rejected there. Assert HTTP and MCP use the same action/cost/read-write classification.
- Before and after each module extraction, report measured do_POST/dispatcher function count and branch count using the same counting method. Counts are evidence, not permission to merge unrelated route groups.
- Run parity and focused regression selectors only after the shared serial test slot is granted. Do not claim runtime, unload, or live dashboard proof from static or unit evidence.

### Current gate state

- T01 inventory: in progress; interim 223 owner labels, 38 body-field gaps; final integrity/sign-off pending.
- Shared descriptor/auth/mode/body/error contract: not frozen.
- T07/T08/T14/T17/T18 owner boundaries: retain as listed above; no cross-owner extraction.
- T13 extraction: not started.
- Test slot: not confirmed.
### T02 async-core ownership update — 2026-10-03

- T02 owns async dispatch/cancel timing in `src/local_ai_hub/async_jobs.py` (candidate commit `f8024d8`: dispatch-deadline recheck, early timer rearm, atomic queued cancellation). T13 must not edit, port, or duplicate these core changes.
- T02 reports its candidate-suite receipts in `artifacts/t02-combined-suite-baseline-handoff.json`. Keep these candidate-only; root integration and root test acceptance are not established by that evidence.
- T13 may own only the agreed HTTP route adapter/dispatch seam after T01 inventory and shared descriptor/auth/mode/body/error contract freeze, with T02's current ownership boundary confirmed. Do not extract the async core.
- Root-current async preimage, integration state, and root receipt remain unverified. No duplicate T13 tests before the shared serial slot.