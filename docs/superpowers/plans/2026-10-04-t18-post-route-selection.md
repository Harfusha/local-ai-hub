# T18 POST Route Registry Plan

**Goal:** Extract `Handler.do_POST` exact-path selection into an immutable POST registry while preserving existing route bodies and response behavior.

**Scope:** T18 candidate worktree only. T18 owns status/dashboard/telemetry and the T27 registry/matcher layer. Registry selects existing branches; it does not move or rewrite T03, T07, T13, or T14 handler implementations. No root edit, test, or merge.

## Pinned preimages

- Root HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; `src/local_ai_hub/http_server.py` SHA-256 `c97aa26a4d84be35fe7bfa1a18fdbb5ae9a5ba393f73d541d38e3f2dcb33d93d`; `Handler.do_POST` lines 2769–5183 (2415 lines).
- Candidate HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`; same source SHA-256 `771d62ea4c5809255e985f40cf46e59a8093af2f5381813e49a1c74bdfaa93f0`; `Handler.do_POST` lines 2720–4689 (1970 lines).
- Root dirty entries: 437. Candidate dirty entries: 503. Counts from `git status --short --untracked-files=all`; unrelated dirt preserved.
- Exact route selection snapshot and method/gate summary: `tests/fixtures/http_post_route_inventory_t18.json`.

## Behavior boundary

- `OPTIONS`: `/api/browser/` prefix or exact `/api/vision/review`; APP, route, host/origin gate, then 204.
- `GET`: `/health` before APP readiness; existing trace/auth rules, public shell, loopback `/api/mode` exception, two parameter prefixes; no GET edits.
- `POST`: Root and candidate pre-dispatch orders differ; exact sequences pinned in the route fixture. Registry selection is inserted only after each pre-existing authorization/recovery precondition and refreshed after the applicable mode gate. Raw bundle import remains on each preimage’s existing fast path; handler and RecoveryJournal order stay unchanged.
- Direct POST selectors are exact paths or exact alias sets. `/api/embed` intentionally selects two branches in order. Conversation pre-dispatch, `_async_delivery`, body/action sub-routing, auth, mode and RecoveryJournal logic remain in place. No POST parameter prefix is added.

## Steps

1. Add golden selector tests and route fixture first. RED observed: test collection fails because `local_ai_hub.http_route_registry` does not exist.
2. Add immutable `POST_ROUTE_REGISTRY` and method/path matcher. Convert only top-level static route conditions to route-ID membership; keep all handler bodies untouched.
3. Run new candidate selector parity tests and focused existing POST contracts. Do not run root tests.
4. Build exact root-current patch from the pinned root preimage in memory; never write root. Record source/test hashes and patch hash.

## Acceptance

- Root and candidate route sets match for every exact POST path; same per-path priority, including duplicate `/api/embed` branches.
- Unknown routes return no registry match and retain existing 404. Non-POST methods return no POST match.
- Existing auth/mode/idempotency and endpoint contracts pass candidate-focused tests.
- Final patch contains only the registry module, selector condition/import changes, route fixture, and selector tests.

## Execution receipt — 2026-10-04

### TDD and candidate tests

- RED command: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_post_route_registry_t18.py` — exit `1`, expected `ModuleNotFoundError: No module named 'local_ai_hub.http_route_registry'` before implementation.
- GREEN selector/parity command: same command — exit `0`, **5 passed in 1.37s**.
- Focused auth/mode/accounting command: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py tests/test_http_tool_accounting_rejections.py` — exit `0`, **39 passed in 2.69s**.
- Combined command: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_admin_action_auth_t18.py tests/test_http_operational_mode_t18.py tests/test_http_tool_accounting_rejections.py tests/test_conversation_continue_route_contract.py` — exit `1`, **39 passed, 3 failed in 9.49s**. Failures: `test_hub_client_continues_through_production_route_and_preserves_transcript`, `test_expired_conversation_is_terminal_through_production_route`, `test_competing_continuation_is_retryable_in_progress_through_production_route`. Diagnostic command with `--showlocals` isolated the first test: exit `1`; the returned start response has `error_code=operational_mode_unavailable` and no `conversation_id`. Failures occur before route-handler dispatch; that T13-owned gate/fixture was not changed. No claim of conversation contract acceptance.

### Exact root-current patch

- Patch: `handoff/T18-root-current-post-route-registry-20261004-v1.patch`, SHA-256 `e2957aa86824c005b497c602143a5f5ea7e36be09de415b4683c3bd4f474c843`.
- Read-only root `git apply --stat`: 4 files, 4314 insertions, 160 deletions. Files: `http_server.py`, new route registry, selector test, golden fixture.
- Read-only `git apply --check --ignore-space-change --whitespace=nowarn`: exit `0` against pinned root preimage. Root source SHA stayed `c97aa26a4d84be35fe7bfa1a18fdbb5ae9a5ba393f73d541d38e3f2dcb33d93d`; no root edits, tests, or merge.
- Expected root `http_server.py` post-image SHA-256 if T20 later applies this exact patch: `55e29fd2ee8e069ea749f29bc7038f480cea7565fedfd76260f4f7d8d9a15361`.

### Candidate post-images

- `src/local_ai_hub/http_server.py`: `1fb254431ebf16d1ed75fc08744f26038de2dcf2e306060bd25e7a5e987759c5`.
- `src/local_ai_hub/http_route_registry.py`: `a0f3c79fd99e33bdbdefc3875278ccb93ba8dfe6bd33be3d3713f87ad37189a9`.
- `tests/test_http_post_route_registry_t18.py`: `66463ed7eccb51a4c2215edeaee484328005ba1eea001df2b0c09f4622d735b9`.
- `tests/fixtures/http_post_route_inventory_t18.json`: `d9ed85d35b85b084affac5a3669dc77f956cda081b15ddceb864a7f543212b14`.
- Candidate broad dirty count was 503 before this registry packet; current count is 508, exactly five new packet files. Existing dirty source remains preserved.

No root test or integration claim. Full runtime and release acceptance still require T20 coordination.

### Conversation-route failure diagnosis — 2026-10-04

The three `test_conversation_continue_route_contract.py` failures are candidate-environment failures before the route matcher, not matcher-parity failures:

- The T18 candidate has no `src/local_ai_hub/operational_mode.py`. The root worktree has that currently untracked T13 file, SHA-256 `0019210f5540b9f0a3aeae119cdcc3ca2d70c9f86305ae45dd89f52ff860d515`, defining `load_operational_mode` and `operational_mode_gate_error`.
- Candidate `http_server.py` imports that module in `_operational_mode_api` (line 190). `_http_mode_gate_error` catches import/load exceptions and maps them to HTTP 503 `operational_mode_unavailable` (lines 252–283). `do_POST` returns that error at lines 2747–2750; `select_http_routes` runs later at line 2751.
- The conversation fixture starts `/api/delegate` without stubbing the operational-mode module. The start response therefore has no `conversation_id`; the three continuation assertions fail during shared setup. This explains the observed failures on the candidate preimage. Root behavior remains unverified; no root test was run.
- T18 made no T13 handler/module change. Keep this integration dependency with T13 ownership. The registry matcher and full root/candidate route inventory remain unchanged.

### T27 row-by-row parity correction — 2026-10-04

This section supersedes the earlier 160-rule/224-path summary and the earlier root-route patch. The prior inventory included `/api/context/pack`, which is outside T18/T27 and must remain T14/Agent-2-owned inline dispatch.

- Pinned root `docs/API_COVERAGE.md` SHA-256 `66b5c89fe088021e5d32feebd1bf953edffad729ec16a55e2b814dc9dacc40f0`: 223 unique `HTTP POST` rows. Candidate `docs/API_COVERAGE.md` SHA-256 `0d04f226f2e065ed917b2b2146338503c84e6adeae6d36377c72f03eb3e158b4`: 222 rows; it omits `/api/admin/mode`. Candidate source route map still has an exact selector rule for that root operation.
- New `tests/fixtures/http_post_api_coverage_route_crosswalk_t18.json` and `handoff/T18-post-api-coverage-route-crosswalk-20261004-v1.csv` map every root API row by operation ID and exact path to ordered root and candidate route IDs and source lines. Result: 223/223 rows mapped; no missing paths; root/candidate route ID order equal for every row. Only duplicate route is `/api/embed`, with both IDs and order preserved. This is path/selector parity only.
- `API_COVERAGE` reports owner evidence `unassigned` for all 223 rows. This conflicts with the older T27 plan count of 195 unresolved; the 28-row ownership discrepancy remains unresolved. Do not infer owner or per-route body/response/idempotence/error contract from route families or counts. The row map records each owner as unassigned.
- `/api/context/pack` is absent from the 223-row API inventory and excluded from the registry, selector cases, and root patch. Its original `if path == "/api/context/pack":` branch remains inline. No Agent-2/T14 body changed.
- Candidate source preimage remains HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`; inherited dirty entries were 508 before this correction. Current candidate dirty count is 510, adding only the crosswalk CSV and JSON. Root worktree was read-only.
- Candidate selector/crosswalk command: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_post_route_registry_t18.py` — exit `0`, **7 passed in 0.87s**. Test covers all 223 mapped rows, root/candidate selector-order equality, duplicate `/api/embed`, POST-only selection, catch-all miss, inline `/api/context/pack`, and auth/recovery/mode gate order.
- Updated root-current patch: `handoff/T18-root-current-post-route-registry-20261004-v1.patch`, SHA-256 `f93ab59b379e5acbb0f2712e4d29bd09c0a56c92a843065cdd251da2072f42a8`. It changes only `http_server.py` route predicates plus the registry/test/fixtures (5 files total); the pack branch hunk is absent. Root pinned `http_server.py` SHA-256 remains `c97aa26a4d84be35fe7bfa1a18fdbb5ae9a5ba393f73d541d38e3f2dcb33d93d`. Read-only `git apply --check --ignore-space-change --whitespace=nowarn` passed, exit `0`; root test/integration not run.
- The three conversation-start failures remain a candidate dependency blocker: candidate lacks T13 `operational_mode.py`; its mode gate returns `operational_mode_unavailable` before matcher. Root contains a dirty T13 module; T18 did not copy or modify it. Conversation contract acceptance remains open until T13 candidate dependency is supplied.

### T27 named-dispatch stage — 2026-10-04

Review found that the earlier immutable selector still fell through to the long `if` chain. Candidate now adds `POST_ROUTE_HANDLER_BOUNDARIES` and `select_post_handler`, with one independently useful T18 telemetry-timeline boundary: `post_telemetry_timeline_1` → `_handle_post_telemetry_timeline`. The old inline branch body moved unchanged into that method; `do_POST` calls the named boundary inside the existing generic-exception try after recovery `begin`. All shared gates and remaining legacy branches stay in place. `/api/context/pack` stays inline/excluded.

Candidate tests added for exact route-to-boundary selection, response status/body and service-call arguments, error propagation, and gate/recovery exception ordering. **Not run** per current instruction. Post-edit static AST parse passed. The earlier 7-pass selector receipt predates this change. See `handoff/T27-staged-dispatch-plan-20261004-v1.md` for staged completion gates and ownership blocker.
