# T01 uncovered operation owner/test handoff — 2026-10-02

Static snapshot only. It preserves all 387 historical gap rows with no behavior selector or owner receipt; operation IDs and individual criteria are in the JSON artifact.

- Source uncovered CSV SHA-256: `E9A32BE7548A4E758CF5A26D4FEB05D7C2D64E69E6CE4EA1B89577A69CFE9C21`.
- Owner/test plan JSON SHA-256: `5835CC1A2AE5220E1813C3B6D3E7DE13836253606D04FE4000D8E4CA22ECE1F4`.
- Current root acceptance batch: 123 selectors; 123 statically mapped; `root_green=0`.
- Historical gap split: 58 targeted candidate rows, 387 without selector/owner receipt, 1 owner-receipt-only row (T13 transcribe). No uncovered operation is ownerless.

## Next owner and criteria

| Owner | Uncovered rows | Surface split | Next acceptance |
|---|---:|---|---|
| T01 | 1 | HTTP GET: 1 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T02 | 3 | HTTP GET: 1; HTTP POST: 2 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T03 | 7 | MCP action schema gap local_ai_repo: 3; MCP action schema gap local_ai_status: 4 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T04 | 75 | HTTP GET: 11; HTTP POST: 61; HubClient method: 3 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T05 | 10 | HTTP GET: 2; HTTP POST: 7; HubClient target: 1 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T06 | 1 | MCP action alias local_ai_command: 1 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T08 | 18 | HTTP GET: 2; HTTP POST: 13; HubClient target: 2; MCP action local_ai_status: 1 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T09 | 5 | HTTP GET: 1; HTTP POST: 4 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T10 | 159 | HTTP GET: 20; HTTP POST: 62; MCP action alias local_ai_repo: 4; MCP action local_ai_repo: 73 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T11 | 13 | HTTP GET: 1; HTTP POST: 12 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T12 | 8 | HTTP GET: 4; HTTP POST: 1; MCP action alias local_ai_task: 3 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T13 | 9 | HTTP POST: 8; MCP action local_ai_task: 1 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T14 | 5 | HTTP POST: 2; MCP action local_ai_artifact: 2; MCP action local_ai_repo: 1 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T15 | 32 | HTTP POST: 11; HubClient target: 2; MCP action alias local_ai_command: 3; MCP action local_ai_command: 16 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T16 | 3 | HTTP POST: 3 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T17 | 11 | HTTP POST: 11 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T18 | 20 | HTTP GET: 8; HTTP POST: 5; MCP action local_ai_status: 4; MCP detail local_ai_status: 3 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T19 | 4 | Generated manifest: 1; HTTP GET: 1; HTTP POST: 2 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T20 | 2 | HTTP POST: 1; HubClient target: 1 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |
| T21 | 1 | HTTP POST: 1 | Add one exact public-operation selector per ID in owner plan JSON; assert same-call dispatch/result, not metadata only. |

## Surface criteria

Each row in the JSON includes its owner, operation ID, handler, metadata node, target test module and acceptance criteria. Surface-level rule: assert the public input, exact dispatched endpoint/payload/defaults/timeout, and same-call output or error; mutation cases use isolated state and verify the resulting state. Aliases, details, schema variants, and generated manifests need separate contract assertions.

## Concrete gaps

- T01 `op-a991c9e8b941` — GET `/api/context/pack`: explicitly excluded; remains visible and uncovered.
- T08 `op-f954480234c9` — GET `/api/agent-state/events/stream`.
- T05 `op-d50cc5e721fb` — GET `/api/agent-state/memory`.
- T10 `op-b86b72558569` — GET `/api/code/ast_outline`.
- T18 `op-411b0d6c8d7d` — GET `/api/db/query`.
- T13 `op-65970ac00a0a` — HTTP POST `/api/task/transcribe`: separate owner receipt exists; root selector still absent, so root-green remains false.

## Boundary

No tests or root writes. These rows stay open until each owning task supplies an asserted selector and T20 records root-current pass receipts. T03 owns schema resolution for its seven coord schema-gap rows, which have candidate tests but remain contract-unresolved.

