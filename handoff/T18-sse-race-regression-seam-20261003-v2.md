# T18 SSE replay/subscribe regression handoff

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `360a58f90d0d6562641e62d15095410fc5dd044a`.
- Owned T18 worktree: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.
- No root edit. Prepared patch only in this worktree.

## Failure receipt and cause

Orchestrator ran:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py tests/test_telemetry_report_bounds_t18.py
```

Result: `1 failed, 9 passed, 9.25s`; failing selector: `tests/test_sse_events_stream.py::test_sse_stream_does_not_lose_event_between_replay_and_subscribe`, assertion at line 131. Receipt: replay page contains seq 1, then keep-alive and timeout, with no `task.updated` frame.

Root `http_server.py` subscribes before calling `event_page`. `AgentStateStore.append` commits, then calls `_publish`, which puts the event into subscribed queues. The root-current dirty regression test currently injects `task.updated` before calling the original `event_page`, so that event is part of the replay snapshot; it does not place the event between the snapshot read and live-queue consumption. The regression seam must call the original `event_page` first, then append/publish. This gives the route a snapshot containing only seq 1 while seq 2 is queued for live delivery.

## Prepared correction

Test-only patch: `handoff/T18-root-test-sse-replay-subscribe-seam-fix-20261003-v2.patch`

SHA-256: `C88CBF13AD1810C487E2407A4F563467A3D0FB6805EFEA1056AA7A372550BDF2`

Changed root path: `tests/test_sse_events_stream.py`. Moves the test append after the captured `event_page` result. No production SSE code change indicated by this regression receipt.

Exact check against current root working tree:

```powershell
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=nowarn -- C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub\handoff\T18-root-test-sse-replay-subscribe-seam-fix-20261003-v2.patch
```

Result: exit code `0`. Patch remains unapplied. No test rerun performed in this task.
