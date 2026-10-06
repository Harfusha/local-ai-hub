# T18 current-root mode POST fixture handoff

Date: 2026-10-01. Test owner: T18 candidate worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`. Root integration and shared test owner: T20. HUB/GPU/user browser not used.

This supersedes the narrower mode overlay receipt in v3. Candidate's old asynchronous POST test was a stale fixture: it expected `_operational_mode_api().set_operational_mode(mode, state_dir)` plus an unload helper on that module. Current root imports `set_operational_mode(state_dir, mode)` directly and performs bounded cleanup through `APP.runtime.unload_configured_models(timeout_seconds=3.0)` while verifying accelerator release. The candidate production route is still behind; T18 changed no production source.

## Current-root source pins

Root HEAD observed: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

- `src/local_ai_hub/http_server.py`: `94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3`
- `src/local_ai_hub/dashboard.py`: `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`

The candidate overlay asserts module origin and these exact hashes before exercising the current root methods. `tmp_path` owns the mode file; HTTP binds only an ephemeral loopback port. Gaming POST asserts partial model cleanup (`model-a` unloaded, `model-b` failed) and unverified embedding/reranker releases; those failures remain visible in the real JSON envelope. The same run checks unauthenticated read-only GET `/api/mode`, wrong action token 401, valid `mode.control` token, persistence and audit.

## Exact overlay command and result

```text
$env:T18_ROOT_SOURCE='C:\Users\Adam\.local-ai-hub\src'; $env:T18_ROOT_HTTP_SERVER_SHA256='94C44910B04F8909778F926E64D3F857975BAA5738B78979427BACE29AA3EDF3'; $env:T18_ROOT_DASHBOARD_SHA256='9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_root_current_mode_overlay_t18.py tests/test_dashboard_mode_playwright_t18.py
```

Result: **2 passed in 2.48s**, exit 0. The Playwright test extracted `DASHBOARD_HTML` from the pinned root module and verified degraded health summary, live transport status, partial gaming feedback, 401 and 503 behavior.

The root-compatible test-only patch below passed read-only `git apply --check` against the root worktree, exit 0. No patch was applied; no test file from the root checkout was run.

- `handoff/T18-root-overlay-dom-test-only-20261001-v1.patch`
- Patch SHA-256: `FEDFA064336E38F67C00E2B83B5FF6B288A598A0848200BD1C3676AC8AAB9CF2`
- Patch adds only three regression files: root HTTP mode overlay test, root-pinned Playwright DOM test, and its Node fixture.

## Candidate's known failing legacy test

It remains explicitly reported, not counted as green or silently deselected:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_operational_mode_t18.py::test_admin_mode_post_starts_unload_after_releasing_guard_and_returns_pending_then_partial
```

Result: **1 failed in 1.36s**, exit 1 (`unload_started.wait(1)` false). That candidate-only route still implements the pre-T13 setter/unload contract. The passing overlay is the current-root replacement fixture and retains partial-cleanup assertions.

Candidate test/fixture SHA-256:

- `tests/test_root_current_mode_overlay_t18.py`: `53762406E12F30E926C2D448D46D8BAAD2B56B0F33D8F93CCE1C12A871A3CDF7`
- `tests/test_dashboard_mode_playwright_t18.py`: `6A5C513A00B32A9E3F475B4421A93BD37D3864875C823BFAF3235052E1AAE257`
- `tests/fixtures/dashboard_mode_playwright_t18.cjs`: `35BDBB553FEEC9DC7849379F78DA4DC720EC4D5441BFE19D8F49D8B9DC8B7799`

The earlier `137 passed, 1 deselected` candidate selector is not a full acceptance receipt. T20 must integrate the test-only patch and produce fresh shared-root receipts. T13 owns mode production changes; no compatibility alias was added.
