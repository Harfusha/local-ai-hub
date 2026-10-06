# T14 context budget boundary — recovery checkpoint

Date: 2026-10-02
Candidate worktree: `C:\Users\Adam\.codex\worktrees\t14-context-budget-recovery\.local-ai-hub`
Candidate base: `8c945bdeb5f92270613e53b307b6f646a4f0e21b` (`origin/master`)
Root snapshot: `01df56605ccf484ebfe2808ac60d696c4e81dffc`

## Owned change

The context response budget passed its final hard-limit fallback through a generic rejection object, discarding the adaptive context identity and file/line citation. T14 adds `adaptive_context_pack` to context-protected fields and emits a bounded rejection projection containing context ID, revision, and at most one complete citation. Raw evidence content and bulk warnings are dropped. The same response remains capped by the requested token estimate.

Changed paths in this candidate:

- `src/local_ai_hub/mcp_server.py`
- `src/local_ai_hub/response_budget.py`
- `tests/test_mcp_response_budget.py`
- `tests/test_response_budget.py`

HTTP routes, `/api/context/pack`, policy prompts, ledger, and caller integration were not edited.

## Regression selector and validation boundary

New test: `test_budget_rejection_keeps_bounded_adaptive_context_identity_and_citation`.

Initial acceptance batch (run in T20 slots B and F; receipts below):

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_response_budget.py tests/test_mcp_compact_transport.py::test_local_ai_repo_context_returns_bounded_deterministic_projection tests/test_mcp_compact_transport.py::test_local_ai_repo_guarded_projection_drops_nested_raw_model_fields tests/test_mcp_compact_transport.py::test_local_ai_repo_context_bounds_oversized_authoritative_fields tests/test_mcp_compact_transport.py::test_local_ai_repo_context_low_budget_preserves_authoritative_envelope
```

No test run outside assigned T20 serial slots. Slot B failed six tests before `_bounded_string` was added; slot F ran after that fix and exposed two missing MCP decision fields. See receipts below.

Static checks after the latest source repair: `git diff --check` exited 0; Python AST parsing reported `AST_OK` for all four candidate Python files. These do not replace pytest evidence.

## Hashes

- Candidate `src/local_ai_hub/response_budget.py`: `934D5DA4D9A031568DE8A6AC05A1B655FB92CA375B99518DF17C1B32C621DD02`
- Candidate `src/local_ai_hub/mcp_server.py`: `BBA5A38D8E48577DA2BE5310C4363A21853B47F8ADDA6240667AFAC54DACBF0E`
- Candidate `tests/test_response_budget.py`: `7FC05067629EC863149C05B0F57797D22F8DA6CABDA77A89730D9534775A11D4`
- Candidate `tests/test_mcp_response_budget.py`: `8F7541B0219BE7D6EB0979659CB81994E47FB537CD13AFAE933A8002D120FD50`
- Root `src/local_ai_hub/response_budget.py` preimage: `4C1A96267E4789752543CCD828EF09F3D54C9FFD701D763D666AF1ED4C7ECE83`
- Root `tests/test_response_budget.py` preimage: `CD89D6190BFED74E25BEB1E00D1B876ED340D1E497F443627F34224783CE745E`
- Candidate patch `T14-context-budget-boundary-recovery-2026-10-02.patch`: `BDAEBB6258926DFCC2911FB02EA963567099011678575C51F5831A5EAC44FC24`

Candidate/root files already differ because their bases and dirty states differ. The candidate patch is not claimed root-applicable; T20 must review/port against a fresh root preimage. Prompt synchronization remains T19-owned. Action-specific MCP output schema and context-output validation remain T03-owned.

## Context identity and E2E boundary

Source acceptance checked without tests: `build_context_request` forwards bounded tenant, task, repository revision, root, clone/worktree/branch/repository/session, phase, focus, preload profile, and delta fields. `ContextCompiler` scopes memory lookup by root/task/tenant/clone/worktree/branch. `compose_task_context` derives its ID from task ID, compiled etag, repository context ID/revision, and evidence IDs; compiled etag includes phase, revision, element IDs, and content. This is source inspection only, not runtime proof.

Exact remaining E2E gaps:

- Existing `tests/test_mcp_compact_transport.py` route calls are mocked; they do not prove a live HTTP server response crosses the MCP transport and fits the returned-token contract.
- Existing `tests/test_unified_task_context_transport.py` composes repository and agent context through a mocked service; it does not exercise the owner-2 `/api/context/pack` HTTP route.
- No live server/MCP test proves context identity and one citation survive the full oversized-response rejection path with `returned_tokens <= requested_tokens`.
- Do not edit owner-2 `/api/context/pack`. T20 must schedule serial test slot before these tests run; current acceptance test selector remains the focused budget/transport command above.

No tests run. No HTTP route or transport files changed.

## T14 owned patch and selector map

- Bounded rejection regression: owned paths `src/local_ai_hub/response_budget.py`, `tests/test_response_budget.py`; selector `tests/test_response_budget.py::test_budget_rejection_keeps_bounded_adaptive_context_identity_and_citation`.
- Budgeted MCP projection regressions: existing selectors `tests/test_mcp_compact_transport.py::test_local_ai_repo_context_returns_bounded_deterministic_projection`, `::test_local_ai_repo_guarded_projection_drops_nested_raw_model_fields`, `::test_local_ai_repo_context_bounds_oversized_authoritative_fields`, and `::test_local_ai_repo_context_low_budget_preserves_authoritative_envelope`.
- Context/cache identity gap: `CompiledContext.etag()` binds phase, repository revision, element IDs, and content; it omits request scope identity (tenant/session, root, clone/worktree/branch/repository, preload profile, focus, and include kinds). Exact follow-up owned paths, if T14 accepts this gap: `src/local_ai_hub/agent_context.py`, `tests/test_agent_context.py`; selector `tests/test_agent_context.py::test_context_etag_separates_request_scope_identity` (new), paired with existing `::test_delta_pack_returns_unchanged_etag`, `::test_unsupported_memory_scopes_require_matching_request_identity`, and `::test_authoritative_memory_is_root_and_task_session_scoped`. The new selector is a prepared requirement, not an existing test or verified failure.
- Task-context composition carries compiled etag into its context ID. Existing contract selectors: `tests/test_unified_task_context.py::test_build_context_request_forwards_task_scope_fields`, `::test_compose_task_context_contains_agent_and_repository_layers`, and `::test_compose_task_context_rejects_revision_mismatch`.
- Live HTTP/MCP end-to-end acceptance remains owner-2 dependent. Keep `/api/context/pack` out of T14 edits; use the existing mocked selectors above until owner-2 publishes a seam or explicit E2E ownership. Do not claim full-route proof from mocked transport tests.

No identity source fix was made in this checkpoint. Tests remain gated by T20 serial slot.

## T14 context/MCP budget contract — candidate implementation

The context projection must keep the response at or below `max_response_tokens`, including after authoritative fields are reattached. On an oversized guarded context response, preserve `success`, `context_id`, `repo_revision`, the first `evidence_id`, and one bounded citation (`path`, line bounds, `source`) inside `adaptive_context_pack` or legacy `context_pack`. Drop evidence content and bulk warnings. Preserve `stale` and delta identity fields when present and when they fit. MCP final projection reattaches only the sanitized pack before its hard-budget pass; protected fields no longer force all warning/path payload into a rejection.

Candidate-owned paths now include `src/local_ai_hub/mcp_server.py` and `tests/test_mcp_response_budget.py`, alongside `src/local_ai_hub/response_budget.py` and `tests/test_response_budget.py`. The owner-2 HTTP route `/api/context/pack` remains untouched.

Exact acceptance selectors, not run:

- `tests/test_response_budget.py::test_budget_rejection_keeps_bounded_adaptive_context_identity_and_citation`
- `tests/test_response_budget.py::test_budget_rejection_keeps_bounded_legacy_context_pack_citation`
- `tests/test_mcp_response_budget.py::test_context_projection_keeps_actual_context_text_after_budget`
- `tests/test_mcp_response_budget.py::test_context_projection_budget_rejection_keeps_bounded_identity_and_citation`
- Existing MCP transport selectors from the prepared command above.

Prepared command for T20 slot:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_response_budget.py tests/test_mcp_response_budget.py tests/test_mcp_compact_transport.py::test_local_ai_repo_context_returns_bounded_deterministic_projection tests/test_mcp_compact_transport.py::test_local_ai_repo_guarded_projection_drops_nested_raw_model_fields tests/test_mcp_compact_transport.py::test_local_ai_repo_context_bounds_oversized_authoritative_fields tests/test_mcp_compact_transport.py::test_local_ai_repo_context_low_budget_preserves_authoritative_envelope
```

This is unit/MCP projection acceptance. It is not live HTTP-to-MCP E2E proof; owner-2 route acceptance remains separate.

T20 serial-slot request sent to the verified `Local AI Hub T20 — release acceptance` thread. T20 replied: slot `T20-SERIAL-20261002-A` is assigned to T04 (waiting longer); T14's exact test batch remains queued. No tests run; wait for explicit next-slot assignment and receipt before treating selectors as run.

Hub audit receipt for this continuation: `local_ai_status(action="brief", max_response_tokens=500, response_profile="compact", reuse_key="t14-status-20261002")` returned `success=true`, Ollama online, `inflight=0`, `queued=0`. One `local_ai_repo(action="review_diff", root="C:\Users\Adam\.codex\worktrees\t14-context-budget-recovery\.local-ai-hub", max_response_tokens=600, response_profile="compact", reuse_key="t14-context-mcp-budget-review-20261002")` did not return within 47 seconds; request was terminated, no evidence ID/terminal result. No retry and no native broad review followed. The earlier hanging context request was not repeated.

## T20 slot B result and repair

T20 assigned exclusive slot `T20-SERIAL-20261002-B`. The exact batch above ran once through `local_ai_command`: exit 1, `.....FF...F....F.FF` (6 failures), duration 7.51 s. Broker response omitted `terminal` and `retryable`; diagnostic artifacts were disabled, output truncated, no failure artifact ID. Before/after hashes matched. Full receipt: `handoff/T14-SERIAL-20261002-B.receipt.json`. No retry or native rerun. T20 explicitly released slot B.

Slot B exposed missing `_bounded_string`; helper was added and validated in slot F. Slot F then exposed final MCP projection dropping `changed_paths` and `warnings`; bounded retention for these decision fields is now added. Current candidate patch SHA-256: `bdaebb6258926dfcc2911fb02ea963567099011678575c51f5831a5eac44fc24`. Current `response_budget.py` SHA-256: `934d5da4d9a031568de8a6ac05a1b655fb92ca375b99518df17c1b32c621dd02`; `mcp_server.py`: `bba5a38d8e48577da2be5310c4363a21853b47f8adda6240667afac54dacbf0e`. AST and whitespace checks passed after this repair. No tests run on this current patch.

Latest T20 coordination update: slot C is closed/released, slot D assigned to T15. Do not infer T14 validation from slot C.

Latest queue update: after T15 slot D, T17 has slot E; this exact T14 patch (`b7a2596c1b6ca47a80435ca40fe61eb26d602a6076736b5c29a5a8bf383803f`) is queued for slot F. Do not start the batch before explicit slot-F start. No post-fix tests have run.

T20 incident update: T17 slot E was misrouted; broker targeted main root, then T17 ran native pytest in its candidate. No valid broker receipt; T17 is barred from further runs. T20 later closed E as invalid acceptance and assigned T14 exclusive slot F after incident closure.

## T20 slot F result and next focused acceptance

Slot F ran once via `local_ai_command`: 17 passed, 2 failed (`changed_paths`, `warnings` missing). T20 explicitly released F. Broker omitted terminal/retryable and failure artifact; diagnostic artifacts were disabled; before/after hashes matched. Exact record: `handoff/T14-SERIAL-20261002-F.receipt.json`. No retry or native rerun.

Current patch requires a new serial slot. Focus only on relevant regression and transport selectors:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_response_budget.py::test_budget_response_preserves_bounded_task_context_contract tests/test_response_budget.py::test_budget_rejection_keeps_bounded_adaptive_context_identity_and_citation tests/test_response_budget.py::test_budget_rejection_keeps_bounded_legacy_context_pack_citation tests/test_mcp_response_budget.py::test_context_projection_keeps_actual_context_text_after_budget tests/test_mcp_response_budget.py::test_context_projection_budget_rejection_keeps_bounded_identity_and_citation tests/test_mcp_compact_transport.py::test_local_ai_repo_context_returns_bounded_deterministic_projection tests/test_mcp_compact_transport.py::test_local_ai_repo_context_bounds_oversized_authoritative_fields tests/test_mcp_compact_transport.py::test_local_ai_repo_context_low_budget_preserves_authoritative_envelope tests/test_mcp_compact_transport.py::test_local_ai_repo_guarded_projection_drops_nested_raw_model_fields
```

This focused command is prepared only; do not run until T20 explicitly assigns the next slot. `/api/context/pack` remains Agent 2-owned.

Latest T20 queue note: G runner is no longer live; T20 will close G as UNKNOWN and assign H. Repaired patch `bdaebb6258926dfcc2911fb02ea963567099011678575c51f5831a5eac44fc24` and 9-selector batch await explicit H confirmation. Do not start before H GO. No native retry, benchmark, or `/api/context/pack` call.

Hash recheck: candidate patch and four changed Python files match the hashes above; `git diff --check` exited 0. No tests run in this update.

## Slot H review note

Slot H ran the nine selectors once: 8 passed, 1 failed. The failure is an assertion expectation, not yet a proven source defect: `test_context_projection_budget_rejection_keeps_bounded_identity_and_citation` first confirms the final result is `<= 220` tokens, then requires `response_budget` metadata. `budget_response` has an existing tested no-op fast path for values already within budget (`test_budget_response_does_not_change_small_values`), which returns the input unchanged. Thus a no-op projection correctly has no `response_budget` field under the current implementation. The new assertion is left unchanged pending acceptance-contract review; no production edits after slot H. Candidate remains unaccepted.

## Source-only contract diagnosis — slot H assertion

- Failing selector input/assertion: `tests/test_mcp_response_budget.py:79-105` sets `max_response_tokens=220`, supplies 12 evidence entries and 12 long warnings; lines `112-114` first assert `json_tokens(result) <= 220`, then require `response_budget.requested_tokens` and `returned_tokens`. Slot-H receipt reports `KeyError: 'response_budget'` at line 113, so the token-bound assertion already passed.
- Budget helper no-op: `src/local_ai_hub/response_budget.py:322-323` estimates the input; lines `347-348` return the value unchanged when `original <= requested`. Existing contract test `tests/test_response_budget.py:33-36` asserts exactly that behavior for a small value, with no added metadata.
- Rejection boundary: `src/local_ai_hub/response_budget.py:264-278` returns result when its final size fits and invokes `_budget_rejection` only when it still exceeds `requested`. `_budget_rejection` at lines `196-212` has metadata variants including a minimal `{}`; line `229-230` attaches `response_budget` only when selected metadata is non-empty. Thus metadata is not guaranteed on a no-op or on the smallest rejection envelope.
- Written policy: `docs/MCP_AND_AGENTS.md:76` requires aggregate bounded responses and defines `max_response_tokens`, minimum, profiles, reuse and delta behavior. It does not require a `response_budget` object when projection did not change the payload. `docs/UPDATE_PROMPT.md:136` likewise requires aggregate budgeting, not unconditional metadata.
- Conclusion: existing implementation/test contract supports omitting `response_budget` when final projected content fits. Slot-H test fixture does not force the final projection above 220 tokens; the failed assertion alone does not show a production defect. Leave assertion unchanged pending owner review, as requested. No source/test edit or rerun performed.

## No-test acceptance review — 2026-10-02

- Reviewed candidate diff: only `src/local_ai_hub/response_budget.py`, `src/local_ai_hub/mcp_server.py`, `tests/test_response_budget.py`, and `tests/test_mcp_response_budget.py` are owned source/test changes. Candidate patch SHA-256 remains `bdaebb6258926dfcc2911fb02ea963567099011678575c51f5831a5eac44fc24`.
- Consumer flow checked: guarded `local_ai_repo` context is sanitized, compacted, authoritative metadata is reattached, sanitized context pack is restored before the final budget pass, then bounded response projection preserves IDs, warnings, changed paths, stale/delta state, degraded/fallback flags, and one citation on rejection. Evidence content and bulk warnings are not retained by rejection projection.
- Tool schema/descriptions remain unchanged; this patch adds no flag, default, or public schema field. `/api/context/pack` HTTP route remains out of scope and untouched.
- Policy/docs cross-check: `docs/MCP_AND_AGENTS.md` already specifies aggregate response budgets, minimum 128, context evidence/identity contracts; `docs/INSTALL_PROMPT.md` documents bounded task context fields; `docs/UPDATE_PROMPT.md` requires checking `max_response_tokens`, `response_profile`, and `reuse_key` in generated schemas. Internal projection behavior adds no policy/schema change, so prompt/docs files remain unchanged.
- Static evidence: `git diff --check` exited 0; four changed Python files parsed with `AST_OK`; patch and file hashes rechecked. No tests run. Slot H remains queued after UNKNOWN slot G; next exact 9-selector command above awaits explicit T20 start.
