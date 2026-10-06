# T14 continuation handoff — 2026-10-02

Worktree: `C:\Users\Adam\.codex\worktrees\t14-context-budget-recovery\.local-ai-hub`
Candidate HEAD: `8c945bdeb5f92270613e53b307b6f646a4f0e21b`

## Owned implementation

- `src/local_ai_hub/response_budget.py`: context-budget rejection retains bounded context ID/revision and the first complete evidence citation. It scans at most 24 evidence entries and drops raw content.
- `src/local_ai_hub/mcp_server.py`: sanitized context pack is restored before the final hard-budget pass; identity/citation fields are protected through rejection.
- `tests/test_response_budget.py`: adaptive, legacy, and incomplete-first/complete-second citation regression cases.
- `tests/test_mcp_response_budget.py`: context projection regression fixture includes 32 `changed_paths`, ensuring original serialized input exceeds 220 tokens; assertions preserve the hard limit, identity, citation, and truthful budget metadata.

`/api/context/pack` and its owner-controlled hunks were not edited. Other dirty worktree state was preserved.

## Static checks

- `git diff --check`: PASS.
- Python AST parse for the four changed Python files: PASS (`AST_OK`).
- No pytest run is accepted for the current complete candidate. All test execution remains subject to a fresh T20 serial GO.

## Test receipts and limits

- Slot H ran a prior MCP batch: 8 passed, 1 failed. The failing fixture did not force pre-budget size above 220; it was corrected afterward. Do not treat the H receipt as proof of the corrected fixture.
- Slot K attempted the corrected MCP fixture once via `local_ai_command`; broker transport closed without a receipt. Status UNKNOWN; no retry/fallback.
- Slot W attempted the distinct citation selector once via `local_ai_command`. Broker returned only `success:false` and truncated budget metadata, with no request/execution ID, `terminal`, `retryable`, exit code, or test summary. Status UNKNOWN; no retry/fallback.
- K and W UNKNOWN states are separate and closed. Do not repeat either exact selector or infer test failure/pass from the tool envelope.

## Next acceptance

Request a fresh T20 slot and fresh pins for distinct, not-yet-attempted selectors. Do not run tests until GO. Do not use native fallback after UNKNOWN results. Keep current hashes below as the pin baseline.

## File SHA-256

- `src/local_ai_hub/mcp_server.py`: `bba5a38d8e48577da2be5310c4363a21853b47f8adda6240667afac54dacbf0e`
- `src/local_ai_hub/response_budget.py`: `b194856374042b145f9951b6594d775a0e2bdb4cd119ad19b01d6314de171853`
- `tests/test_response_budget.py`: `f5ed53dd0bba3bd764a69da6cb708e8a9031752a5b6b2365a1a3b8584d671742`
- `tests/test_mcp_response_budget.py`: `bc96010c28be28fda63e07b5d4a3d1861ff2b2c6cd210984c706f8c4cbd87530`

## HTTP endpoint ownership and current acceptance

The latest owner assignment includes `/api/context/pack`. Read-only inspection at candidate HEAD confirmed its request validation and response wiring in `src/local_ai_hub/http_server.py`; this file has no current diff. Existing endpoint-level regression selector:

`tests/test_context_delivery.py::test_context_http_rejects_malformed_max_tokens_and_guard_fields`

It asserts malformed `max_tokens` and unguarded fields return bounded 400 errors and that phase/focus-only guarded input succeeds. The existing smoke selector `tests/test_reliability_core.py::test_http_runtime_smoke` also posts to `/api/context/pack`, but is broader. Neither selector was run in this continuation. Request a fresh serial slot and pins before execution.

Endpoint source SHA-256: `45bc723b8be231ee61dfad488688fa3daee390de79ae4f517b9b97c45ccd9721` (unchanged; no route edit).
Endpoint test SHA-256: `b72217b755bbe72ca53bd2ec8d21ecc94ef201fb3945646e1cbb5976222591d4` (unchanged).

## Current owner candidate — typed budget and scoped cache identity

Latest owner assignment expands T14 to the `/api/context/pack` boundary and request context identity. Candidate stays in this worktree; no root checkout edits.

New behavior:
- HTTP `max_tokens` now requires a JSON integer (bool, float, numeric string rejected with terminal 400/retryable false); negative integer remains separately rejected.
- `CompiledContext.etag()` now incorporates a SHA-256 digest of task/root/tenant/clone/worktree/branch/repository/session/phase/focus/preload/include kinds/include diagnostics/changed paths. Raw identity values are not serialized. Same-scope `since_hash` retains unchanged behavior; cross-scope etags differ.
- Existing budget rejection behavior remains: aggregate token cap, bounded context identity/citation, raw content omitted, errors and retryability preserved when they fit.

New regression selectors:
- `tests/test_context_delivery.py::test_context_http_rejects_malformed_max_tokens_and_guard_fields` now also rejects float, numeric-string, and bool budgets; it retains the valid integer phase/focus request path.
- `tests/test_agent_context.py::test_context_etag_separates_request_scope_identity` checks ten scope changes plus unchanged same-scope delta.
- `tests/test_response_budget.py::test_budget_rejection_uses_later_complete_legacy_citation` uses a distinct legacy-pack fixture; the earlier adaptive selector W remains closed UNKNOWN and is not repeated.

Suggested one-slot acceptance command (unrun; requires fresh T20 GO):

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_context.py::test_context_etag_separates_request_scope_identity tests/test_agent_context.py::test_delta_pack_returns_unchanged_etag tests/test_context_delivery.py::test_context_http_rejects_malformed_max_tokens_and_guard_fields tests/test_context_delivery.py::test_model_failure_returns_deterministic_degraded_pack tests/test_agent_context.py::test_disabled_agent_state_returns_stateless_repo_context_warning tests/test_response_budget.py::test_budget_rejection_uses_later_complete_legacy_citation
```

Static checks on the candidate: `git diff --check` PASS; Python AST parse PASS for all eight changed source/test Python files. No new tests have run. Existing H/K/W receipts remain separate; K and W UNKNOWN selectors are not retried.

Patch against candidate HEAD (not asserted applicable to root): `handoff/T14-context-budget-candidate-2026-10-02.patch`, SHA-256 `0b96ec5b6dbd6c614076d6a25be6014420840d373b731f2bff7bfd3d0c281835`.

## Final T14 candidate pins — 2026-10-02

This section supersedes the preceding candidate patch hash and test list. Additional review closed the cross-scope delta-cache gap: history entries now store the request-scope digest with their elements. A `since_hash` from a different scope does not filter current elements through another scope's cached history; same-scope unchanged/delta behavior remains.

Updated regression coverage:
- Scope etag test uses populated compiler context, asserts 13 request-identity dimensions yield distinct etags, same-scope unchanged remains true, cross-scope delta returns the full current scoped elements, and raw identity values do not appear in serialized context.
- HTTP endpoint test rejects float, numeric-string, boolean, and negative budgets with bounded terminal/non-retryable 400 responses; valid integer guarded request remains covered.
- Budget rejection tests cover bounded retryable backend error preservation and a late complete citation from the legacy context pack. Earlier K/W UNKNOWN selectors remain excluded.

One proposed T20 serial acceptance command, unrun:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_context.py::test_context_etag_separates_request_scope_identity tests/test_agent_context.py::test_delta_pack_returns_unchanged_etag tests/test_context_delivery.py::test_context_http_rejects_malformed_max_tokens_and_guard_fields tests/test_context_delivery.py::test_model_failure_returns_deterministic_degraded_pack tests/test_agent_context.py::test_disabled_agent_state_returns_stateless_repo_context_warning tests/test_response_budget.py::test_budget_rejection_preserves_bounded_error_and_retryability tests/test_response_budget.py::test_budget_rejection_uses_later_complete_legacy_citation
```

No tests run for these latest edits. `git diff --check` PASS; AST parse PASS for all 8 changed Python files. Candidate HEAD: `8c945bdeb5f92270613e53b307b6f646a4f0e21b`. Candidate patch: `handoff/T14-context-budget-candidate-2026-10-02.patch`, SHA-256 `d8076b6bdc74e7d62f799dc53c9a91200c640c873b280071ae6c9a3892afe7f2`. Patch is based on this candidate HEAD; do not assume it applies to a different/root checkout.


## T20 slot #5 receipt — selector collection error

Preflight matched HEAD `8c945bdeb5f92270613e53b307b6f646a4f0e21b`, candidate patch SHA `d8076b6bdc74e7d62f799dc53c9a91200c640c873b280071ae6c9a3892afe7f2`, this handoff pre-run SHA `A25A8CA6D9854E4780EE24CA7FBDAA621DAE6CD44CA5490006D42CBA9E0F3232`, and selector runner count 0. The one exact GO command exited 1 before collection: `test_disabled_agent_state_returns_stateless_repo_context_warning` was pointed at `tests/test_context_delivery.py`, but is defined in `tests/test_agent_context.py`. Pytest reported `no tests ran`; this is a command/selector-path error, not a test failure or pass. Post-run HEAD and patch SHA matched; runner count 0. Slot released. Corrected selector path is reflected above; any rerun requires a fresh T20 GO and pins.
## Complete source/test pins for next GO

Verified at candidate HEAD `8c945bdeb5f92270613e53b307b6f646a4f0e21b`:

- `src/local_ai_hub/agent_context.py`: `164d88058cfd168b3f60541d2f2b641a5c293901bb4a10ccd92719381f35cf46`
- `src/local_ai_hub/http_server.py`: `9a0c8d7d6cb794e27017fab68d2e34043371bc2c961a0cd0b849724af461c267`
- `src/local_ai_hub/mcp_server.py`: `bba5a38d8e48577da2be5310c4363a21853b47f8adda6240667afac54dacbf0e`
- `src/local_ai_hub/response_budget.py`: `b194856374042b145f9951b6594d775a0e2bdb4cd119ad19b01d6314de171853`
- `tests/test_agent_context.py`: `4964f52b98326b64241122daa25d940f0e2a58f386c8bcc9e55b1ff6dc6c8d0b`
- `tests/test_context_delivery.py`: `09892ddd997be199913a016fe642f9e8d4a468450add5fd7949a7809faa26f5b`
- `tests/test_mcp_response_budget.py`: `bc96010c28be28fda63e07b5d4a3d1861ff2b2c6cd210984c706f8c4cbd87530`
- `tests/test_response_budget.py`: `5c40e6bfc577700075e68060e60d4c30de3171c9cc289b909a8a0390a4a1ef3b`

T20 GO #7 was aborted before test launch because these file pins were absent from its specified handoff snapshot. HEAD and patch pins matched; selector runner count was zero. No test was run in slot #7. This omission is repaired for the next GO; handoff SHA changes accordingly.

## T20 GO #8 result and next candidate repair

Preflight matched the prior pins and runner count was 0. The exact seven-selector batch ran once: exit 1, `F.....F`, 5 passed and 2 failed in 7.16s. Failures were limited to the new scope-cache test comparing volatile `ContextElement.freshness`, and the legacy citation test expecting `response_budget.original_tokens` at a 128-token limit where that optional field is omitted. These were test expectation/fixture defects; no UNKNOWN receipt. Slot released; no retry/fallback.

Repairs in the current candidate: scope test compares stable element IDs/content while still asserting cross-scope full context and unchanged same-scope behavior; legacy citation fixture now uses 220 tokens so the truthful `original_tokens` metadata fits. Source implementation unchanged from GO #8 candidate.

## Current post-repair pins

HEAD `8c945bdeb5f92270613e53b307b6f646a4f0e21b`; updated candidate patch SHA-256 `4d1df59415fe512cce7725facbda2f55f2e9c502395ff47dfc40ad67237cb8a6`.

- `src/local_ai_hub/agent_context.py`: `164d88058cfd168b3f60541d2f2b641a5c293901bb4a10ccd92719381f35cf46`
- `src/local_ai_hub/http_server.py`: `9a0c8d7d6cb794e27017fab68d2e34043371bc2c961a0cd0b849724af461c267`
- `src/local_ai_hub/mcp_server.py`: `bba5a38d8e48577da2be5310c4363a21853b47f8adda6240667afac54dacbf0e`
- `src/local_ai_hub/response_budget.py`: `b194856374042b145f9951b6594d775a0e2bdb4cd119ad19b01d6314de171853`
- `tests/test_agent_context.py`: `aa976a155206c46422476984a90423e1b61c775e3d89354325e09e13e37aac8d`
- `tests/test_context_delivery.py`: `09892ddd997be199913a016fe642f9e8d4a468450add5fd7949a7809faa26f5b`
- `tests/test_mcp_response_budget.py`: `bc96010c28be28fda63e07b5d4a3d1861ff2b2c6cd210984c706f8c4cbd87530`
- `tests/test_response_budget.py`: `bcfd89791a576c79941e9494a78f86c94a320d23d112e5792758179e7506b7aa`

`git diff --check` and AST parsing of all eight changed Python files pass after repair. Only the two repaired selectors need a fresh T20 GO; do not rerun the five passing selectors in GO #8.

## T20 GO #10 result and bounded-candidate fix

Preflight matched all pins; selector runner count was 0. The exact two-selector batch ran once: exit 1, `.F`, scope etag/cache test passed, late legacy citation test failed because a compact candidate fit before `_budget_rejection` and retained the incomplete first evidence item. Post-run pins were unchanged and runner count was 0; slot released without retry.

Source fix: every reduced compact and pointer candidate now passes through `_retain_bounded_context_citation`, which replaces protected adaptive/legacy packs with the bounded identity and first complete citation projection before budget fit is decided. This closes the path that bypassed rejection-only sanitation. Existing regression is unchanged; current retry must use a fresh T20 GO.

Current source/test pins and candidate patch:
- Candidate HEAD: `8c945bdeb5f92270613e53b307b6f646a4f0e21b`
- Candidate patch SHA-256: `865037a89a10dac0fff323f827d2c0113e5a717ea96dd66432287b1113b0f7b7`
- `src/local_ai_hub/agent_context.py`: `164d88058cfd168b3f60541d2f2b641a5c293901bb4a10ccd92719381f35cf46`
- `src/local_ai_hub/http_server.py`: `9a0c8d7d6cb794e27017fab68d2e34043371bc2c961a0cd0b849724af461c267`
- `src/local_ai_hub/mcp_server.py`: `bba5a38d8e48577da2be5310c4363a21853b47f8adda6240667afac54dacbf0e`
- `src/local_ai_hub/response_budget.py`: `bd090576cc96e9ad9e0ce4164ce9969b115d726d97d4e939aa06e7c2cdc01a31`
- `tests/test_agent_context.py`: `aa976a155206c46422476984a90423e1b61c775e3d89354325e09e13e37aac8d`
- `tests/test_context_delivery.py`: `09892ddd997be199913a016fe642f9e8d4a468450add5fd7949a7809faa26f5b`
- `tests/test_mcp_response_budget.py`: `bc96010c28be28fda63e07b5d4a3d1861ff2b2c6cd210984c706f8c4cbd87530`
- `tests/test_response_budget.py`: `bcfd89791a576c79941e9494a78f86c94a320d23d112e5792758179e7506b7aa`

After the source fix, `git diff --check` PASS and AST parse PASS for all eight changed Python files. No tests run on this latest source candidate. Request a fresh serial slot for the seven-selector acceptance command above.

## T20 GO #12 receipt — final acceptance batch

Preflight matched candidate HEAD `8c945bdeb5f92270613e53b307b6f646a4f0e21b`, patch SHA `865037a89a10dac0fff323f827d2c0113e5a717ea96dd66432287b1113b0f7b7`, handoff SHA before receipt `07181c6d6af7ffe1efc1fdee88727730b7522cceb4ba62a87381432aec568c7a`, all eight source/test pins, and selector runner count 0.

Exact command ran once:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_context.py::test_context_etag_separates_request_scope_identity tests/test_agent_context.py::test_delta_pack_returns_unchanged_etag tests/test_context_delivery.py::test_context_http_rejects_malformed_max_tokens_and_guard_fields tests/test_context_delivery.py::test_model_failure_returns_deterministic_degraded_pack tests/test_agent_context.py::test_disabled_agent_state_returns_stateless_repo_context_warning tests/test_response_budget.py::test_budget_rejection_preserves_bounded_error_and_retryability tests/test_response_budget.py::test_budget_rejection_uses_later_complete_legacy_citation
```

Result: exit 0, `7 passed in 8.15s`. Post-run HEAD, patch, and all eight source/test hashes match their pre-run pins; post-run selector runner count 0. Slot released. No retry or fallback.
