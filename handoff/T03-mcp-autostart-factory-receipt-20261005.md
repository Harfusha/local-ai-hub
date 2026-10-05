# T03 MCP client-factory acceptance receipt

Date: 2026-10-05 (Europe/Prague)
Assigned worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`
Branch: `codex/t03-contracts-resume`
Base HEAD: `d68ee694c6d3f75db5c1ab2f63497226880e5010`

## Ownership and change scope

This is a candidate-only acceptance receipt. No source or test code changed in this continuation. T03-owned behavior under test: `_build_mcp_client()` passes the configured tenant, config path, and `auto_start=True` to `HubClient`. The existing targeted regression test asserts all three values. `client.py` remains outside this T03 hunk; its Git status is clean. T04 owns client lifecycle/request-ID implementation. `/api/context/pack` remains T14-owned and untouched.

The two whole-file hashes below fingerprint dirty candidate files and include unrelated inherited hunks. They are not whole-file ownership claims. Other existing dirty worktree content remains preserved.

| File | HEAD preimage SHA-256 | Candidate postimage SHA-256 | Git status |
| --- | --- | --- | --- |
| `src/local_ai_hub/mcp_server.py` | `986b1eb79abf753f43d84c108e17e7be3b24cbde549bc258ded32f778f57b84c` | `24CB51FC19931D5E27508E48A3AAE59CDFA06914E7B8FD11A717C3A7EF8244E2` | modified |
| `tests/test_mcp_compact_transport.py` | `569d848e8f2192d2ab51b5f7392e1294f01602e911378bc09a519087855102b8` | `CF8E7C906C27969E70F9FBEC33EF0C2D2B701C5125B0B86A4B1B32E09E8D3636` | modified |

## Exact candidate validation

Command, brokered by `local_ai_command(action="run")`:

```powershell
$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_compact_transport.py::test_mcp_client_factory_forwards_tenant_and_config
```

Observed result: **1 passed in 1.64s**, exit code `0`. Hub execution ID: `f1d2c1994eca4e85b33f27924bbef394`; request ID: `req_a2f9239d80dd`; candidate repository revision: `5978118306487305899c0002bbe96e011cd364a344596f429341cfd635d2d9d1`.

This exact selector was not part of the prior 28-test resumed API/client batch or the 274-test candidate batch. No other test was run in this continuation. Post-run file hashes match the table above.

## Acceptance status and preserved failures

This selector confirms the candidate factory forwarding contract only; it is not live-daemon or root integration proof. Prior candidate receipt remains **28 passed, 2 failed in 9.03s**; the alias selector was subsequently corrected and passed **1 passed in 2.18s**. The remaining `local_ai_rag` generic-versus-action output-schema mismatch stays deferred per user decision and excluded from T03 acceptance. Root acceptance remains open under T20; no root files or tests were touched here.
