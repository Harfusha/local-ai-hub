# T01 next public operation gap — 2026-10-02

## Updated priority — MCP coord gaps

- T20 has verified the preceding GET `/api/agent-state/tasks` root selector: **1 passed in 4.54s** after its spy accepted and asserted the forwarded `query` keyword.
- Next priority is `local_ai_coord::task_rollback`, operation `op-28d63e90525c` (primary owner T08). It exercises restore-to-checkpoint behavior and persisted rollback event.
- Paired guard selector `test_local_ai_coord_feature_disabled_rejects_valid_action_before_backend_dispatch` covers disabled `local_ai_coord` rejection before backend dispatch; the tool-level manifest row is `op-a9ceb516370a` (owner T03).
- Exact candidate selectors: `tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_task_rollback_restores_and_persists_previous_checkpoint` and `tests/test_mcp_coord_operation_acceptance.py::test_local_ai_coord_feature_disabled_rejects_valid_action_before_backend_dispatch`.
- Both selectors are in the previously completed 63-selector candidate run (**63 passed in 25.96s**). Neither is root-green; root integration awaits T20's occupied pytest slot. Root-current test-only patch and scratch receipt: `T01-mcp-coord-gap-handoff-20261002.md`.

## MCP/coord inventory refresh — 2026-10-02

- Added 32 named forwarding tests, 21 MCP protocol tests for canonical actions and aliases, and 7 schema-gap diagnostics. Did not run inventory `--check` or touch `docs/API_COVERAGE.md`.
- Current selector map: 59 of 446 historical gap rows linked, 58 with targeted selectors, 387 still unlinked; 127 unique candidate selectors. Root-green remains 0.
- All seven T03-owned `local_ai_coord` schema-gap rows now have candidate selectors; schema/ownership resolution remains T03’s. Seven additional protocol tests cover canonical actions outside the historical gap map.
- The 60-test batch awaits T20’s slot release. Current root-current test-only patch preimage and scratch receipt are pinned in `T01-mcp-coord-gap-handoff-20261002.md`.

## Previous priority — HTTP GET tasks (historical snapshot)

- Priority scan across the current 642-row inventory found no CLI operation rows without exact test selectors. Highest-risk uncovered candidates include POST `/api/agent-state/cleanup` (`op-79a6996c295f`, T08), POST `/api/agent-state/swarm/dispatch` (`op-b1b285bc55a8`, T08), and MCP `local_ai_command::stop_daemon` (`op-5b53e1c4c62b`, T15): all can change persistent state or process state and need owner-specific isolation.
- Selected unlinked public operation: **HTTP GET `/api/agent-state/tasks`**, operation ID `op-8a32e6e43634`, owner T08.
- Priority reason: useful read path for task status/stale filtering used by coordination; authenticated, read-only route with user-visible filtering/serialization behavior. It is the safest high-utility next gap to prove without touching T08/T15 mutation paths.
- Exact focused behavior selector: `tests/test_http_route_operation_acceptance.py::test_http_get_agent_state_tasks_forwards_filters_and_serializes`.
- Test verifies query parsing (`status=active`, `limit=7`, `include_stale=true`), forwarded filter values, HTTP 200, and serialized task response. It does not use metadata parametrization.
- Current map: 642 inventory rows; 69 rows linked to six focused test files; 64 unique selectors. Historical 446-row gap map: 3 exact selector/owner-receipt links, 443 without a behavioral selector; root-green remains 0.

## T01 candidate receipt

- Worktree HEAD: `689165fbe18101feacf5f489847a4890fc27ed1f`.
- Preflight active pytest count: 0.
- Exact command:

  ```powershell
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_route_operation_acceptance.py::test_http_get_agent_state_tasks_forwards_filters_and_serializes
  ```

- Result: **1 passed in 3.85s**, exit code 0.
- Postflight active pytest count: 0; test hash stayed `46D5E8BB9BF7B68A7BFAB9C49D528FED6CA5723C00AA9769DA305C83556DB633`; T01 HTTP source hash stayed `B5F0A63A0E8F68CE71B81C6B2EC49DE3F9FF8E30AAC90D244298AD790857A35D`.

## T20 root integration patch, prepared only

- Patch: `handoff/T01-root-agent-tasks-get-coverage.patch`, SHA256 `6FA93F13C9EE2FAD5DC36450EFC5613C1EFE27AFED01B3E8224A65B35DEE6BE9`.
- T01 test preimage SHA256: `00286DF5140B8858C409410D5B4527E236D170B11DB7494743CB4F46031C5296`.
- Updated T01 test SHA256: `46D5E8BB9BF7B68A7BFAB9C49D528FED6CA5723C00AA9769DA305C83556DB633`.
- Root-current test preimage SHA256 (after T20's prior event-page patch): `BD01B4DBE8A0DBA1AF8B1171ED5F15B9ED1888A06AF05A7C7BC9A9CC84DCF679`.
- Scratch `git apply --check --whitespace=error`: exit 0. Predicted root test postimage SHA256: `17545CF91DD56C8922F34DBFF3AC5B92E4467F264EEAB92F1FF97F6B0A41652C`.
- Root HEAD remained `01df56605ccf484ebfe2808ac60d696c4e81dffc`; root test stayed at the preimage hash. No root edit or test by T01.

## Mapping and remaining gaps

- Builder now labels test-file matches as targeted selectors and leaves execution status to run receipts; it no longer calls every selector in a previously passed file suite “passed.” Builder SHA256: `E835669E670F11849D86A09B4F6C543C505134A6EA470F3E4ACF566A662AB0E2`.
- Current selector map JSON SHA256: `6F850BEE860AEC79CD37ABB785C85C8192A4D603817577674C35D46AAFC4A572`.
- Unmapped-operation dedupe JSON SHA256: `84D624DF2ED227A4CF4A72C1E7F7E595CB1C04A19CB80D88832A6FAEB7397151`.
- Remaining behavior gaps include 443 historical rows without selectors, plus root integration and live/runtime evidence. Metadata node IDs remain metadata-only.
