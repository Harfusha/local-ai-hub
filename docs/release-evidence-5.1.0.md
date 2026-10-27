# Local AI Hub 5.1.0 — Release Evidence

**State:** source candidate tested; hosted CI, verified plan completion and live activation remain open.
**Candidate revision:** `e4cc6a52051e1db0aad5e0c7a9c4a6374fb751c8` (evidence below refers to that source commit or explicitly identified earlier commits).
**Target:** `5.1.0`.

## Current candidate evidence — 2026-10-27

- [CI for `e4cc6a52`](https://github.com/Harfusha/local-ai-hub/actions/runs/40525847943) is pending. [CI for `f3098253`](https://github.com/Harfusha/local-ai-hub/actions/runs/40523028067) was still running Ubuntu 3.14 at the last check; previous runs for `93b253f6` and `341d44f7` failed.
- Surface audit and inventory passed **774 tests** on `f3098253`. The dashboard, loading-state and plan verification tests passed **25 tests** on `e4cc6a52`, and `tools/check_dashboard.py` passed. These checks do not prove the complete backend plan lifecycle.
- An untouched archive of `e4cc6a52` passed `python tools/release_check.py --strict-tree`; selftest passed **6/6** on that candidate. The working-checkout release check reported existing `build/` and `dist/` directories, which were preserved.
- Wheel built from the clean `e4cc6a52` archive: SHA256 `1a05c73d1fd7df151d6888f10adb3a19bab53dd9cc6e699c037f99ba0a3d7c2c`. An isolated Python 3.13 environment and `tools/wheel_smoke.py` returned `success=true`, `smoke=passed`, planner schema passed and five MCP tools. MCP status was degraded in that smoke run; it is not live acceptance.
- `docs/perf_candidate_json_budget.json` records 1,000 independently measured pairs, parity, p95 1.72x and p99 1.95x. It applies to source `94a485ffecf6bc3c9810718b2f658b6df0120b64` and closes only the JSON-budget tail gate.
- Pre-restart `/health` returned success/version `5.1.0`; `hubctl status` reported PID `18096`, and its command points to this repository's `.venv` and source tree. The running process has not loaded candidate code yet.
- Pre-restart MCP `plan_list` on this root failed with `acceptance_criteria is not valid for action='plan_list'` (request on 2026-10-27). Candidate source includes the transport metadata fix; live MCP verification remains open.
- Current screenshot, config/state baseline, safe restart, post-restart process/source proof, dashboard plan create/list/edit check, and receipt-gated Agent OS completion remain open. Several active chats are using the shared Hub, so restart is deferred until they finish.
- Plan file status is a declaration: direct edits and checkpoint synchronization do not yet enforce authentic source verification and target integration. The dashboard labels unverified completion accordingly; it does not repair the missing backend gate.

## Historical verification receipts

| Check | Result | Evidence |
|---|---:|---|
| Planner, storage, schema, host hooks, Agent OS, multi-worktree, and daemon regressions | PASS | `170 passed, 5 skipped` on 2026-10-27; includes the hashed, atomic pending-contract retry record; skips require symlink privilege or POSIX/Windows-only primitives. |
| Current daemon and receipt regression suites | PASS | `232 passed, 13 skipped` on 2026-10-27 across daemon lifecycle, command concurrency, agent ergonomics, and SDK routes. |
| Public surface policy and inventory | PASS | `790 passed` on 2026-10-27. `tools/audit_agent_surface.py` reports `success: true`, `errors: []`. |
| Wheel smoke contract | PASS | `20 passed` on 2026-10-27. |
| Python compile | PASS | `python -m compileall -q src tools tests`, exit 0. |
| Pyflakes | PASS | `python -m pyflakes src tools`, exit 0. |
| Hub selftest | PASS | `tools/selftest.py`, 6/6 checks. |
| Prompt policy synchronization | PASS | `tools/sync_prompt_policies.py --check`. |
| Isolated wheel and MCP stdio smoke | PASS | `local_ai_hub-5.1.0-py3-none-any.whl`, 1,744,973 bytes, SHA256 `278c327c5541284f4fcac7fd2a3501f9a5f77b9a74bef6d62134b998b9431105`; isolated venv `pip check` has no broken requirements; MCP advertises five tools and returns version `5.1.0`. |
| Release check | PASS | `python tools/release_check.py --allow-installed`; pre-existing `build/` and `dist/` were temporarily preserved outside the checkout and restored. |
| Static checks and Hub selftest | PASS | `compileall`, `pyflakes`, prompt policy sync, agent surface audit, and six Hub selftest checks pass on 2026-10-27. |
| Installed Hub after restart | ONLINE | `hubctl status`: PID `26384`, version `5.1.0`, Ollama online, eight models installed, `qwen2.5-coder:3b` active. `tools/doctor.py` confirms server, compact MCP surface, model backend, and state stores healthy with no warnings. |

The smoke wheel is retained outside the checkout at `%TEMP%\lah-5.1.0-candidate-20261027-codex\wheelhouse`. The old `dist/` wheel and its historical SHA are not evidence for this candidate.

## Historical release gate observations

GitHub Actions run [#170](https://github.com/Harfusha/local-ai-hub/actions/runs/40410655500) failed on the pre-fix revision `cb3c25d9a3021a08f474e40a2047c2f9945314bf`. Run [#173](https://github.com/Harfusha/local-ai-hub/actions/runs/40419902289) failed on the first pushed candidate. Run [#174](https://github.com/Harfusha/local-ai-hub/actions/runs/40421458008) had one stale test failure: it expected caller-provided summary text to mint a native verification receipt without broker provenance. The test now asserts fail-closed rejection and verifies no receipt mapping is written. A fresh CI run is required for this corrected candidate.

The historical live model check and dashboard screenshot were not used as current release claims.
