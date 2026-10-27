# Local AI Hub 5.1.0 — Release Evidence

**State:** source candidate tested; hosted CI, verified plan completion and live activation remain open.
**Candidate revision:** `ff0ef061b72418d71ff9422757432d7057534ec1` (evidence below refers to that source commit or explicitly identified earlier commits).
**Target:** `5.1.0`.

## Current candidate evidence — 2026-10-27

- [CI for `ff0ef061`](https://github.com/Harfusha/local-ai-hub/actions/runs/40531160997) is queued. The earlier runs for [`f3098253`](https://github.com/Harfusha/local-ai-hub/actions/runs/40523028067) and [`e4cc6a52`](https://github.com/Harfusha/local-ai-hub/actions/runs/40525847943) failed on Ubuntu 3.14.
- Surface audit and inventory passed **774 tests** on `37a6d9c9`; the plan binding/Agent OS/MCP cohort passed **24 tests** on `ff0ef061`. The earlier dashboard, loading-state and plan verification checks passed **25 tests** on `e4cc6a52`. These checks do not prove the complete backend plan lifecycle.
- A clean archive of `37a6d9c9` passed `python tools/release_check.py --strict-tree` and selftest **6/6**. The working-checkout release check reported existing `build/` and `dist/` directories, which were preserved. Exact `ff0ef061` release verification remains open.
- Wheel built from the clean `37a6d9c9` archive: SHA256 `643592a7d3a0099604e9e8c992267bcfe5f091349da3fe67d5ff8f970cc0a5ae`. An isolated Python 3.13 environment and `tools/wheel_smoke.py` returned `success=true`, `smoke=passed`, planner schema passed and five MCP tools. This is not live acceptance and predates `ff0ef061`.
- `docs/perf_candidate_json_budget.json` records 1,000 independently measured pairs, parity, p95 1.72x and p99 1.95x. It applies to source `94a485ffecf6bc3c9810718b2f658b6df0120b64` and closes only the JSON-budget tail gate.
- Pre-restart `/health` returned success/version `5.1.0`; `hubctl status` reported PID `18096`, and its command points to this repository's `.venv` and source tree. The running process has not loaded candidate code yet.
- Pre-restart MCP `plan_list` on this root failed with `acceptance_criteria is not valid for action='plan_list'` (request on 2026-10-27). Candidate source includes the transport metadata fix; live MCP verification remains open.
- Current screenshot, config/state baseline, safe restart, post-restart process/source proof, dashboard plan create/list/edit check, and receipt-gated Agent OS completion remain open. Several active chats are using the shared Hub, so restart is deferred until they finish.
- Plan file status is a declaration: direct edits and checkpoint synchronization do not yet enforce authentic source verification and target integration. The dashboard labels unverified completion accordingly; it does not repair the missing backend gate.
- The earlier detached agent-evaluation worktree at `1e6584ac` is merged into master. Its remaining tracked two-file diff has the same stable patch ID as integrated commit `c3a0f648`; it is already incorporated, not a new implementation. The checkout and its potentially ignored local files remain preserved, so this is not an archival or cleanup claim.

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
