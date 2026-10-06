# T18 root-pinned overlay and dashboard DOM receipt

Date: 2026-10-01. Candidate owner: `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`. Root integration and shared root-test owner: T20. HUB intentionally skipped.

This supersedes the mode/route status in v2. No root files were edited. No root test file was invoked: both checks below were T18 candidate-owned pytest fixtures that imported and SHA-pinned the current root modules; mode state lived under pytest `tmp_path`, and HTTP used an ephemeral loopback port.

## Exact root source pins

Root HEAD observed: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

- `src/local_ai_hub/http_server.py`: `94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3`
- `src/local_ai_hub/dashboard.py`: `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`
- `src/local_ai_hub/agent_events.py`: `02A25102B888B23FE99B8C508F59AEDD846BA24FD38A268BCC6893B0877E0A38`
- `tests/test_agent_event_page_t18.py`: `39BE401F6709F46F52FFAE904CF87D7DB5B9D329DF381206E98EB633C2CA0B68`

The event-page route and root regression fixture are already integrated in the current dirty root. `event_page` supports snapshot `through_seq`; GET forwards cursor/limit/upper bound and enforces a 1 MiB serialized response limit. The fixture covers envelope, paging, gaps, snapshot stability, limits, byte budget and unavailable/oversize states. The old pre-T20 route patch remains stale; do not apply or duplicate it.

## Root-pinned live HTTP and DOM checks

Command (run from the candidate worktree):

```text
$env:T18_ROOT_SOURCE='C:\Users\Adam\.local-ai-hub\src'; $env:T18_ROOT_HTTP_SERVER_SHA256='94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3'; $env:T18_ROOT_DASHBOARD_SHA256='9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_root_current_mode_overlay_t18.py tests/test_dashboard_mode_playwright_t18.py
```

Result: **2 passed in 2.63s**, exit 0. The overlay asserts both module origins and exact hashes. It uses actual root `load_operational_mode` / `set_operational_mode(state_dir, mode)`, local unauthenticated read-only GET `/api/mode`, wrong-token 401 JSON, scoped `mode.control` action-token POST, actual persistence in `tmp_path`, and checks the authorization audit. The Playwright fixture extracts exact root `DASHBOARD_HTML`; a degraded health payload projects `#overviewHealthLevel=Degraded` while transport pill remains `live`; gaming transition, partial cleanup feedback, 401 and 503 UI projections all pass.

Candidate-only Playwright command with root-pin environment cleared:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_dashboard_mode_playwright_t18.py
```

Result: **1 passed in 1.99s**, exit 0.

## Remaining mode POST blocker

The candidate legacy test is intentionally visible as failing, not silently treated as accepted:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_operational_mode_t18.py::test_admin_mode_post_starts_unload_after_releasing_guard_and_returns_pending_then_partial
```

Result: **1 failed in 1.36s**, exit 1; `unload_started.wait(1)` is false. Candidate HTTP still contains the stale route/unload behavior. This does not block the separate root-pinned overlay, which asserted current root origin and passed. Do not add a production compatibility alias. The previous candidate suite result is **137 passed, 1 deselected** only; it is not whole-lane completion.

## Candidate changed paths and SHA-256

- `tests/test_http_operational_mode_t18.py`: `F4FD42094DEF7915B23A9912037EB4EBF397C8881A264C87D34C25A6E2DDD0D4`
- `tests/test_status_snapshot_quality.py`: `2B8CCDCB4EC6A521AD797D535F8530E1DCDDA90D0A14CD04DC884E47D4314311`
- `tests/test_root_current_mode_overlay_t18.py`: `BEF656871DC1A8438147E7F5A0BA81E4B1ADFD9FA72EB3A9CEE5C5E9A7F24C7C`
- `tests/test_dashboard_mode_playwright_t18.py`: `6A5C513A00B32A9E3F475B4421A93BD37D3864875C823BFAF3235052E1AAE257`
- `tests/fixtures/dashboard_mode_playwright_t18.cjs`: `35BDBB553FEEC9DC7849379F78DA4DC720EC4D5441BFE19D8F49D8B9DC8B7799`

No source, database, shared listener, GPU, HUB or user-browser activity. T20 still owns root test integration/serialization. Full T18 completion remains open pending the explicit current-root integration receipts.
