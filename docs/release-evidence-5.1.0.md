# Local AI Hub 5.1.0 — Release Evidence

**State:** source candidate tested; hosted CI, verified plan completion and live activation remain open.
**Candidate revision:** `7e30585b` (evidence below identifies its source commit; later changes require fresh verification).
**Target:** `5.1.0`.

## Current candidate evidence — 2026-10-27

- A wheel built from a clean Git archive of `7e30585b` has SHA-256 `1a17d891f2334402bc6f6b8691378eeb2f5c0d6a5f6e646fed56312d28c658f9`; installation in a fresh venv, `pip check` and `tools/wheel_smoke.py` passed. Smoke reported `tool_count=5` in its isolated degraded environment; this is not live runtime acceptance. A separate clean archive passed strict-tree release check and selftest **6/6**.
- [CI for `7e30585b`](https://github.com/Harfusha/local-ai-hub/actions/runs/40546801072) is running; its Ubuntu 3.14 result and complete matrix are not yet established. Linux process-parent handling and a late HTTP watchdog race have regression coverage, but their relationship to every previous CI failure remains to be confirmed by the full run.
- Subsequent planner, storage, Agent OS, host and Superpowers test cohort on `c42faaab` passed **88 tests**, with one Windows directory-symlink test skipped because the account lacked symlink privilege. These results do not establish authenticated delivery completion.
- [CI for `2dfc4ee8`](https://github.com/Harfusha/local-ai-hub/actions/runs/40538366360) failed on Ubuntu 3.14: stdio cleanup compared a supervisor PID to the Hub owner PID, a concurrent delegate request failed before transport write, and Serena failure accounting reported zero instead of one. [CI for `093a16bb`](https://github.com/Harfusha/local-ai-hub/actions/runs/40539833709) subsequently failed on cleanup and transport. Later commits addressed observed Linux parent lookup, a transport watchdog race and test isolation; current CI must verify the integrated result.
- Surface audit and inventory passed **774 tests** on `dd06af10`; the plan binding/Agent OS/MCP cohort passed **25 tests** on `354e73e1`. The earlier dashboard, loading-state and plan verification checks passed **25 tests** on `e4cc6a52`. These checks do not prove the complete backend plan lifecycle.
- A clean archive of `dd06af10` passed `python tools/release_check.py --strict-tree` and selftest **6/6**. The working-checkout release check reported existing `build/` and `dist/` directories, which were preserved.
- Wheel built from the clean `dd06af10` archive: SHA256 `72b5a4905687b4cd84cd9c7dab9ce6541b1521d0d1b1bef62375f30433b0d608`. A fresh isolated Python 3.13 environment passed `pip check`; `tools/wheel_smoke.py` returned `success=true`, `smoke=passed`, planner schema passed and five MCP tools. This is not live acceptance.
- An isolated supervisor and browser session using the earlier `354e73e1` wheel and a synthetic Git repository displayed two separate plans named `Release`, identified by their plan IDs. A task declared done without proof appeared as `Done · Unverified`, and the plan progress showed `0% verified complete` and `1 awaiting verification`. The isolated supervisor and Hub were terminated using their own verified owner records. This visual check is not a screenshot or acceptance of the shared live installation.
- `docs/perf_candidate_json_budget.json` records 1,000 independently measured pairs, parity, p95 1.72x and p99 1.95x. It applies to source `94a485ffecf6bc3c9810718b2f658b6df0120b64` and closes only the JSON-budget tail gate.
- Pre-restart `/health` returned success/version `5.1.0`; `hubctl status` reported PID `18096`, and its command points to this repository's `.venv` and source tree. The running process has not loaded candidate code yet.
- Pre-restart MCP `plan_list` on this root failed with `acceptance_criteria is not valid for action='plan_list'` (request on 2026-10-27). Candidate source includes the transport metadata fix; live MCP verification remains open.
- Current screenshot, config/state baseline, safe restart, post-restart process/source proof, dashboard plan create/list/edit check, and receipt-gated Agent OS completion remain open. Several active chats are using the shared Hub, so restart is deferred until they finish.
- Plan file status is a declaration: direct edits and checkpoint synchronization do not yet enforce authentic source verification and target integration. The dashboard labels unverified completion accordingly; it does not repair the missing backend gate.
- Normal setup checks Superpowers for Codex and Gemini CLI when their executables are on PATH. Codex has no version pin, so the implementation checks marketplace and installed versions and reports indeterminate outcomes. On `01a073de`, a real Gemini CLI 0.65.0 installed Superpowers `v7.0.1` into an isolated home via the Windows Node launcher; `extensions list` reported it enabled for user and workspace, and a second check performed no install. This does not verify the user's absent Gemini installation or actual hook delivery. Codex reports enabled Superpowers `7.0.1` and a second enabled `7.0.0`; neither entry was changed.
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
