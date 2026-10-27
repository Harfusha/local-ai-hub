# Local AI Hub 5.1.0 — Release Evidence

**State:** candidate validation in progress; CI and runtime acceptance remain open.
**Revision for wheel evidence below:** `50ce188493b9d000b21599fb572d47aad23f4d7f` (superseded; current source needs fresh wheel and CI evidence).
**Target:** `5.1.0`.

## Current candidate evidence — 2026-10-27

- `tests/test_surface_audit_policy.py tests/test_surface_inventory.py`: **774 passed**.
- Clean `git archive` snapshot: `python tools/release_check.py --strict-tree` passed. The checkout retains its existing ignored `build/` and `dist/`.
- Wheel built from the source revision above: SHA256 `1be43ab48fcf40a2d98695d7019a5b735a26cd9319cb6d088bbdabe8a277b1e1`. Isolated-venv `tools/wheel_smoke.py` returned `success=true`, `smoke=passed`, version `5.1.0`, and five MCP tools. The wheel is retained under `%TEMP%/lah-release-f14c726ef5c04476b213966b02d324e5/wheel/`.
- [CI run #178](https://github.com/Harfusha/local-ai-hub/actions/runs/40479922045) failed the Ubuntu 3.14 full suite; twelve other matrix and coverage jobs passed. Its annotations identify generated-policy/status expectations, Serena fixture timing, command cleanup and async child cleanup. Subsequent fixes require a fresh run and wheel.
- The historical JSON-budget artifact at source `01a72dec90252019060fb40a08a8c4a10f520228` used a synthetic baseline and is invalid. Its replacement, `docs/perf_candidate_json_budget.json`, records 1,000 independently measured pairs from clean source `94a485ffecf6bc3c9810718b2f658b6df0120b64`, with parity, p95 1.72x and p99 1.95x on the recorded Windows host. This is candidate-specific performance evidence, not full release or live-runtime acceptance.
- Runtime restart, current dashboard screenshot, Agent OS completion, and preserved-data comparison are not yet established for this candidate.

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
