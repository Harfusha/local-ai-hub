# Root-current T18 DB query handler packet — 2026-10-04

## Selection evidence

The user designated `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md`, section `### T18 — Status, dashboard, telemetry a administrace`, as authoritative. Its acceptance explicitly assigns bounded read-only DB query authorization and time/row/byte budgets (line 527). `tests/fixtures/http_post_api_coverage_route_crosswalk_t18.json` maps `/api/db/query` to operation `op-6de9fa7594c4`, root and candidate route ID `post_db_query_1`; generated API metadata still marks owner evidence `unassigned`. Extraction does not rewrite ownership metadata or T03 contract fields.

This is read-only route behavior. Existing shared auth, mode and RecoveryJournal prelude remains in place. No T03/T07/T13/T14/T08/Agent-2 implementation is moved or modified. `POST /api/telemetry/tool-accounting` remains T07-owned; admin-mode remains T13-owned. `/api/context/pack` remains excluded and inline.

## Immutable packet

Patch: `T18-root-current-db-query-handler-20261004-v1.patch`

SHA-256: `3CAAC817B8959A16A5B1F22B8EEEDC9844F4CE1059DE7DC5A0089E4BC5906538`

Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`

| Path | Root preimage SHA-256 | Packet postimage SHA-256 | T18 delta |
|---|---|---|---|
| `src/local_ai_hub/http_server.py` | `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24` | `804466F124B000B690B2B22EA7EEC5F024530AD1E0479A1D66082CD164C7BD1C` | Add `_handle_post_db_query`; route-ID dispatch reuses existing post-timeline shared dispatch point; remove only old `/api/db/query` inline body. |
| `src/local_ai_hub/http_route_registry.py` | `46AD21C6AFB648C2436D207E2BC83491CAFAF718B818F51707502738C372E4BA` | `A8E147F223BB5B1D63D9C47DDDA79045B718D9B0A415D8BA8F4FB964B969F30E` | Add only `post_db_query_1` → `/api/db/query` and named handler mapping; order before timeline, matching legacy branch order. |
| `tests/test_http_post_db_query_t18.py` | Absent | `D190FDE52D4BE7EC9C4F518D4F6C24A6216881A08E8278B839CE923C8039A711` | Test selection, DB/query defaults and coercion, HTTP 200/result forwarding, and exception propagation. |

## Preserved contract

`do_POST` readiness, auth, trace/request ID, JSON validation, mode rejection (`/api/db/query` remains in the gaming-safe read POST set), telemetry accounting fast path, tenant, recovery claim and debug-trace setup all precede named dispatch unchanged. Handler keeps defaults `db=agent_state` and `query=SELECT name FROM sqlite_master WHERE type='table'`, string coercions, `_handle_db_query` call, HTTP 200 and exact result envelope. Exceptions still reach the same shared handler error boundary. The read-only authorizer/budget implementation itself is untouched. No other route body moved.

## Verification

- TDD RED: new focused tests failed on missing named mapping/handler.
- Candidate focused command: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_post_route_registry_t18.py tests/test_db_query_bounds_t18.py tests/test_http_post_db_query_t18.py` — **17 passed in 1.41s**. Added explicit assertions for auth → JSON parse → mode gate → recovery → named dispatch order, DB query gaming-safe mode classification, and shared generic exception boundary.
- Root-current `git apply --check` against pinned worktree bytes — exit `0`; `git apply --stat` — 3 files, 48 insertions, 4 deletions. Packet not applied. No root DB tests or runtime proof.

## Remaining POST ownership gates

- `post_telemetry_tool_accounting_1` / `op-04438ec90d60`: T07 owns accounting and RecoveryJournal/idempotency (root ownership receipt lines 87–88).
- `post_bundle_import_1` / `op-e64c615a36e2`: T07 owns import and RecoveryJournal/idempotency (same receipt).
- `post_admin_mode_1` / `op-8bf1bb5e54e6`: T13 route implementation (root ownership receipt line 85).
- `post_config_update_1` / `op-ff52947bcad7`, `post_control_1` / `op-1c75a1cf3cab`, `post_models_manage_1` / `op-5b6baefe1fcd`, and maintenance IDs `post_maintenance_optimize_db_1` / `op-8974a873ebe3`, `post_maintenance_purge_cache_1` / `op-0d0d6f0e1bd8`, `post_maintenance_resolve_errors_1` / `op-b5d302dc5a8c`: API metadata owner is `unassigned`; obtain per-route handler owner plus T07 side-effect/replay disposition before extraction. T03 contract-field gaps remain separate.
- `POST /api/context/pack`: T14/Agent-2 exclusive; excluded.

T18 stays OPEN. This packet covers one additional T18 route; it does not establish full `do_POST` parity.
