# T18 root-current SSE and telemetry handoff

## Scope and ownership

- Root: `C:\Users\Adam\.local-ai-hub`
- Candidate worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`
- Root HEAD: `360a58f90d0d6562641e62d15095410fc5dd044a`
- Candidate HEAD: `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`
- No root files were edited, no patch was applied to root, and no commit or restart was made.
- Root already has unrelated dirty changes; preserve them. At final preflight, dirty relevant paths: `src/local_ai_hub/app.py`, `src/local_ai_hub/dashboard.py`, `src/local_ai_hub/http_server.py`, `src/local_ai_hub/telemetry.py`, `tests/test_sse_events_stream.py`, and untracked `tests/test_telemetry_report_bounds_t18.py`.
- `tests/test_sse_events_stream.py` was dirty at final preflight. Current root hash: `BCEE7A41E7A561DE6E1F4C5F7C663CCFE518CAC9616F48064A5CD86CB67EEECC`; retain the user's current edits. The prepared test patch applies cleanly against it.

## Reproduced failures

On root HEAD `360a58f90d0d6562641e62d15095410fc5dd044a`, the five root-current selectors failed: **5 failed in 8.66s**.

1. `tests/test_sse_events_stream.py::test_sse_stream_replays_and_receives_live_events`
2. `tests/test_sse_events_stream.py::test_sse_stream_does_not_lose_event_between_replay_and_subscribe`
3. `tests/test_sse_events_stream.py::test_sse_stream_replays_all_bounded_pages`
4. `tests/test_sse_events_stream.py::test_sse_stream_timeout_bounds_queue_wait`
5. `tests/test_telemetry_report_bounds_t18.py::test_report_budget_truncation_advances_cursor_after_retained_rows`

The first four failures share one cause: root `http_server.py` calls legacy `APP.agent_state.events(..., limit=1000)` once instead of paging through `event_page`. That bypasses the replay/subscribe race seam, misses events beyond one page, and the timeout event omits `next_seq`. The telemetry failure is in `_bound_telemetry_report`: it advances `next_offset` by retained-row count even for cursor-based pages; it must clear the offset and recompute `next_cursor` from the last retained row.

## Prepared patches

All four patches passed `git apply --check --whitespace=nowarn` against the current root working tree at final preflight. They remain unapplied.

| Patch | SHA256 | Intended scope |
|---|---|---|
| `handoff/T18-root-current-sse-replay-bounds-20261003-v1.patch` | `8D70AD8C0F05FB47A6A2FF651679996BA75BE38A97BF321CF011ACA6A96A349A` | Root path `src/local_ai_hub/http_server.py`; replace one-shot 1000-event replay with bounded `event_page` loop, preserve snapshot watermark, include `next_seq` on timeout; 49 insertions, 9 deletions |
| `handoff/T18-root-current-sse-page-test-20261003-v1.patch` | `9734AB97115C727BF28D08806674583FF578ED18000CC5C2C7F4313228FB0FAC` | Root path `tests/test_sse_events_stream.py`; add `sqlite3` import and bounded-page 1001-event regression test |
| `handoff/T18-root-telemetry-report-cursor-budget-20261002-v1.patch` | `5C68B2319A407836CF97AFD81B575EC2BB829EB304B458F548B6A2A065E2DF3E` | Root path `src/local_ai_hub/telemetry.py`; for cursor pages, clear offset and recompute cursor from last retained row; 15 insertions, 1 deletion |
| `handoff/T18-root-telemetry-report-cursor-budget-test-only-20261002-v2.patch` | `DBF914CA219290CCDBE0A66BE18FEC5691CA7013F162BD7A7BC04A5E5D7AE52E` | Root path `tests/test_telemetry_report_bounds_t18.py`; add 52-line cursor budget regression test |

Exact per-patch apply-check commands, all exit code 0 (`apply-check PASS <filename>`):

```powershell
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=nowarn -- C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-current-sse-replay-bounds-20261003-v1.patch
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=nowarn -- C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-current-sse-page-test-20261003-v1.patch
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=nowarn -- C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-telemetry-report-cursor-budget-20261002-v1.patch
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=nowarn -- C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-telemetry-report-cursor-budget-test-only-20261002-v2.patch
```

## Overlay verification

To avoid touching root, both production patches were applied only inside an automatically cleaned temporary overlay under the candidate worktree. Overlay source hashes:

- `telemetry.py`: `07D8651FE93B42363873348088611E54D9376CB52B820C01BD81D703637BC48A`
- `http_server.py`: `BE41F8EF7A782EDF3E577FCF8D91CCF521DDD9C249BACDA395E444A710FF4227`

The same five selectors against root source overlaid with those two production patches passed: **5 passed in 0.70s**. Overlay application used `git -C <candidate-worktree> apply --directory=<temporary-overlay-relative-path> <production-patch>` for each patch, then a Python pytest launcher loaded the overlaid `http_server.py`/`telemetry.py` with root-current modules and ran the five selectors listed above. Exact ephemeral temp-directory name and launcher command were not retained in the receipt; overlay file hashes and selector list are retained here. An initial overlay attempt applied the telemetry patch at the wrong path, leaving the root telemetry hash unchanged; that attempt failed one telemetry selector and is superseded by the corrected overlay run above.

## Separate `/api/status` defect

The `/api/status` degraded-success issue is separate from this SSE/telemetry patch set. On the root daemon, `/api/status?scope=process` returned HTTP 200 with JSON `success=false`; multiple dependency probes reported `probe_timeout`. The older T18 candidate status diagnostic changes/tests are in the candidate's dirty worktree, but these four patches do not alter that code or establish `/api/status` acceptance. The root `/api/status` cause remains unresolved; no daemon restart or root edit was performed for this SSE/telemetry handoff.

## Shutdown relevance

Candidate `app.py` already shuts down `_status_dependency_executor` with `wait=False, cancel_futures=True` and bounds helper-thread joins to 1.5 seconds. No additional shutdown/thread-pool issue was established as a cause of these five SSE/telemetry failures; no change prepared.

## Root hashes at final preflight

- `src/local_ai_hub/agent_events.py`: `10A8899F4C41020633C74745CE77406BB7FD3792D63FB5388C05C6F4AE0DC451`
- `src/local_ai_hub/http_server.py`: `FF4AF5B5797DD27C01242756D6B83346EC8BD0B37B6F8EE122F7878CD06A9901`
- `src/local_ai_hub/telemetry.py`: `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281B`
- `src/local_ai_hub/app.py`: `1D58B5BB39ADA2ABCCBEC668F0AE653A7C06AAAA258EBB152FDAA4DC69DD0E62`
- `src/local_ai_hub/dashboard.py`: `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`

Handoff is patch-only. Root integration and any subsequent validation remain unperformed.
