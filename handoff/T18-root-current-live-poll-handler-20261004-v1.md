# Root-current T18 live poll handler packet — 2026-10-04

## Owner and API row review

User-authoritative scope is `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md`, section `### T18 — Status, dashboard, telemetry a administrace`, covering dashboard polling/SSE and telemetry. `handoff/T18-T31-route-symbol-owner-parity-20261003-v1.md` explicitly maps `GET /api/live` to the T18 dashboard event-poll consumer contract. API row is operation `op-5d550dcacf01`, path `/api/live`, handler `do_GET`; its generated API `Owner task` remains `unassigned` and is not treated as ownership evidence. Registry exact path equals API row; query parameters remain parsed by `do_GET`, then passed separately. API row linked only metadata coverage and did not assert this handler behavior; this packet adds that behavior coverage.

T01 route artifact used only to check operation/path metadata, not ownership. `TelemetryStore.live()` is the read-only data call (source AST shows no `flush` or write calls); no T07 service/idempotency code changed. No overlap with T03/T07/T08/T13/T14/T17/T21. `/api/context/pack` untouched.

## Immutable root-current packet

Patch: `T18-root-current-live-poll-handler-20261004-v1.patch`

SHA-256: `ED5535ACFCCDE20E4D6440C46A2D9DDC72C574CB3241C0DCE5C04DD5CAD83C01`

Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. `git apply --check` against current root bytes exited `0`; patch not applied.

| Path | Root preimage SHA-256 | Predicted postimage SHA-256 | Delta |
|---|---|---|---|
| `src/local_ai_hub/http_server.py` | `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24` | `AC6DFA1923E87CB9433519C0B4A9B6F9E7D17A31B86F97885FCDB525708870E4` | Add `_handle_get_live`; named dispatch after query parse inside existing GET error boundary; remove only old `/api/live` branch. |
| `src/local_ai_hub/http_route_registry.py` | `46AD21C6AFB648C2436D207E2BC83491CAFAF718B818F51707502738C372E4BA` | `8A8C5DEC080CC559F00C9F87B0A7210A965CBFF10BA8BFE1CB3B7ACAA7E9F255` | Add immutable exact `/api/live` mapping and GET handler selector. Existing POST timeline rule unchanged. |
| `tests/test_http_get_live_t18.py` | Absent | `ABCC8431457371F941EED40C79AB04839FA2E4CE94C75CF3A953B7E319977D5B` | Test exact path, cursor/default/clamp, payload/status, malformed cursor and service error propagation, auth/mode/trace/parse/recovery/error-boundary order. |

## Contract parity

Readiness/auth/mode/trace/query parse order in the root handler stays in place; named dispatch occurs after those gates within the existing `try`. GET has no RecoveryJournal/idempotency claim; test confirms no recovery call was introduced. `/api/live` remains absent from operator and gaming-read GET path sets, so mode policy is unchanged. Handler preserves `after` default `0`, `limit` default `200`, `monitoring.live_max_batch` default `200`, integer parsing, `min(limit, max_batch)`, `TelemetryStore.live(after, limit)` call, raw page response body and HTTP `200`. Parse/service exceptions remain in the same existing error boundary.

## Candidate verification and T20 coordination

- TDD RED observed: selector returned `None`, handler missing; focused contract module had 3 intended failures and gate-order test passed.
- Focused candidate group: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_http_get_live_t18.py tests/test_http_get_live_status_t18.py tests/test_http_post_route_registry_t18.py tests/test_db_query_bounds_t18.py tests/test_http_post_db_query_t18.py tests/test_http_status_diagnostics_t18.py` — **29 passed in 3.34s**.
- Root test not run. T20 root status-selector slot remains independent; this patch and predicted postimages are pinned to the same unchanged current root preimage, not integrated. `git apply --stat`: 3 files, 85 insertions, 5 deletions.

This is one T18 read-only route slice. Overall T18/router migration remains OPEN.
