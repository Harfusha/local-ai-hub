# T18 `/api/status` degraded snapshot diagnosis

## Ownership and scope

- Root examined read-only: `C:\Users\Adam\.local-ai-hub`, HEAD `360a58f90d0d6562641e62d15095410fc5dd044a`.
- Owned checkout: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.
- No root changes. Existing T18 worktree edits preserved. Only this handoff note added during this turn.
- Local AI Hub tools ignored per user instruction.

## Root-current cause

`GET /api/status?scope=process` without `detail=summary` routes to `APP.status(scope=scope)` in `src/local_ai_hub/http_server.py` (root lines 2133–2160). Root `src/local_ai_hub/app.py` defines a 250 ms dependency deadline, an 8-worker executor, and up to 32 in-flight dependencies (lines 69–71). The full status path probes runtime first, then schedules 27 other probes onto that 8-worker executor under a shared 250 ms phase deadline (around lines 850–990). The response sets `success` false when any dependency is degraded.

The earlier root daemon receipt recorded HTTP 200 with JSON `success=false`; six dependencies reported `probe_timeout`: `ollama_profile`, `repo_cache`, `code_index`, `deterministic`, `recovery`, and `embeddings`. Root source maps an unfinished callback at the shared deadline to `probe_timeout`, its fallback, and `degraded=true`; the aggregate then makes `success=false`. Thus the false result is caused by timed-out status probes, not the HTTP route returning an error. The present static evidence does not include per-probe elapsed or queue-wait times, so it cannot distinguish callback runtime from executor queue delay for those six keys.

## Safe disposition

No root-current `/api/status` fix patch prepared. Increasing the 250 ms deadline or the worker limit without per-probe timing is speculative and changes the bounded status contract. Forcing `success=true` would conceal dependency degradation and conflict with current tests that expect a timeout to produce a degraded result. Existing candidate-only status diagnostic edits add sanitized failure reasons/types; they do not prove or remove the six root probe timeouts.

T02 serial test/measurement GO was not present; no tests or benchmarks run. Prepared exact command for the next authorized slot:

```powershell
python -m pytest -q tests/test_status_snapshot_quality.py::test_slow_status_dependency_degrades_within_deadline_and_keeps_shape tests/test_status_snapshot_quality.py::test_status_uses_one_deadline_across_slow_dependencies tests/test_http_status_diagnostics_t18.py::test_status_route_preserves_dependency_diagnostics
```

This existing set checks deadline/degradation/route diagnostics. It does not establish which live callback exceeded the deadline; a per-probe timing receipt is still required before selecting a corrective timeout or executor change.

## Previously prepared T18 patch artifacts

These are the four SSE/telemetry patches prepared by this task. All were checked against root HEAD `360a58f` and remain unapplied. There is no `/api/status` corrective patch in this handoff.

| Absolute path | SHA-256 |
|---|---|
| `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-current-sse-replay-bounds-20261003-v1.patch` | `8D70AD8C0F05FB47A6A2FF651679996BA75BE38A97BF321CF011ACA6A96A349A` |
| `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-current-sse-page-test-20261003-v1.patch` | `9734AB97115C727BF28D08806674583FF578ED1800CC5C2C7F4313228FB0FAC` |
| `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-telemetry-report-cursor-budget-20261002-v1.patch` | `5C68B2319A407836CF97AFD81B575EC2BB829EB304B458F548B6A2A065E2DF3E` |
| `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-telemetry-report-cursor-budget-test-only-20261002-v2.patch` | `DBF914CA219290CCDBE0A66BE18FEC5691CA7013F162BD7A7BC04A5E5D7AE52E` |

Their exact apply-check commands and pass receipts are in `T18-root-current-sse-telemetry-20261003-v1.md`.
