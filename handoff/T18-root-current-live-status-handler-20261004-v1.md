# Root-current T18 live-status handler packet — 2026-10-04

## Owner and route evidence

User-authoritative scope: `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md`, `### T18 — Status, dashboard, telemetry a administrace`, names `http_server.py` and status dependencies/degraded contract. T18/T31 ownership receipt `handoff/T18-T31-route-symbol-owner-parity-20261003-v1.md` explicitly assigns `GET /api/live/status` to T18 status view contract and coverage. API operation is `op-4f432e2ad35d`; API metadata `Owner task` remains `unassigned` and was not edited. This T18 owner receipt scopes the change; T01 API artifact is used only for operation/path identification, not ownership confirmation.

## Immutable root-current packet

Patch: `T18-root-current-live-status-handler-20261004-v1.patch`

SHA-256: `83DC0B4701961EF6D59FA10B7A8FAB22C35E698F86C3A469778AD2E4297D9A5E`

Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. `git apply --check` against current root bytes exited `0`; patch not applied.

| Path | Root preimage SHA-256 | Predicted postimage SHA-256 | T18-owned change |
|---|---|---|---|
| `src/local_ai_hub/http_server.py` | `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24` | `47F25EB0AE256E50C30DF49829317BB6FCA858076C9FA3C5C98F29136FD82BE5` | Add `_handle_get_live_status`; add exact GET named dispatch after `parse_qs` inside existing shared try; remove original exact branch. |
| `src/local_ai_hub/http_route_registry.py` | `46AD21C6AFB648C2436D207E2BC83491CAFAF718B818F51707502738C372E4BA` | `EC2C5DBA33446F89F2C166274F0F818942B94D50DB5F4B26DC2DE3A34230EFAC` | Add immutable `/api/live/status` → handler boundary and exact path selector. Existing POST timeline registry unchanged. |
| `tests/test_http_get_live_status_t18.py` | Absent | `15BBBE8A6B3F45F69766F3DD2E26D497D2BD2AB34CCE1D5CF9A49ED3E2A7DBFF` | Test exact-path selection, query defaults/aliases, 200 degraded snapshot, HTTP concurrency field, error propagation, mode classification, and shared order/error boundary. |

## Parity preserved

Root's existing readiness, authorization, mode gate, trace, query parsing, and error handling remain in source order. Dispatch uses parsed path only, after auth/mode/trace/query parse and inside the existing `try`. No recovery journal applies to this read-only GET; test pins no recovery call. Handler keeps `light` values `1/true/yes`, default false, `scope` default `process`, `APP.realtime_status` call, optional `LocalAIHTTPServer.concurrency_stats()` addition, and HTTP 200 with the returned status envelope, including degraded results. Exceptions remain inside the existing shared GET error boundary. `/api/context/pack` untouched.

## Candidate verification and T20 gate

- Candidate focused group: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_status_t18.py tests/test_http_status_diagnostics_t18.py tests/test_http_post_route_registry_t18.py tests/test_db_query_bounds_t18.py tests/test_http_post_db_query_t18.py` — **25 passed in 1.97s**.
- Candidate focused GET/status pair alone — **8 passed in 0.46s**.
- Root selector reserved for T20 one-shot GO: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_status_t18.py`. No root test run and no integration. T20 was sent patch/preimage/postimage/test hashes; root slot currently queued behind another active root owner.

T18 remains OPEN. This is one independent read-only status handler slice, not whole-router or runtime acceptance.
