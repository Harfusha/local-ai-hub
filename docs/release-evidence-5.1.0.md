# Local AI Hub 5.1.0 — Release Evidence

**State:** candidate validation; source changes are ready for review, hosted CI after push is still required.
**Base revision:** `cb3c25d9a3021a08f474e40a2047c2f9945314bf` (`master`).
**Target:** `5.1.0`.

## Current verification receipts

| Check | Result | Evidence |
|---|---:|---|
| Planner, storage, schema, host hooks, Agent OS, multi-worktree, and daemon regressions | PASS | `169 passed, 5 skipped` on 2026-10-27; skips require symlink privilege or POSIX/Windows-only primitives. |
| Public surface policy and inventory | PASS | `790 passed` on 2026-10-27. `tools/audit_agent_surface.py` reports `success: true`, `errors: []`. |
| Wheel smoke contract | PASS | `20 passed` on 2026-10-27. |
| Python compile | PASS | `python -m compileall -q src tools tests`, exit 0. |
| Pyflakes | PASS | `python -m pyflakes src tools`, exit 0. |
| Hub selftest | PASS | `tools/selftest.py`, 6/6 checks. |
| Prompt policy synchronization | PASS | `tools/sync_prompt_policies.py --check`. |
| Isolated wheel and MCP stdio smoke | PASS | `local_ai_hub-5.1.0-py3-none-any.whl`, 1,742,469 bytes, SHA256 `a8f2dbf38ab417e15ac80a9049bdc6e700f30cc0b73d9f6f05ae6a107eeeebdc`; isolated venv `pip check` has no broken requirements; MCP advertises five tools and returns version `5.1.0`. |
| Installed Hub after restart | ONLINE | `hubctl status`: PID `1560`, port/service reachable, version `5.1.0`; eight models installed, no active model. |

The smoke wheel is retained outside the checkout at `%TEMP%\local-ai-hub-5.1.0-candidate-20261027\wheelhouse`. The old `dist/` wheel and its historical SHA are not evidence for this candidate.

## Open release gate

GitHub Actions run [#170](https://github.com/Harfusha/local-ai-hub/actions/runs/40410655500) failed on the pre-fix revision `cb3c25d9a3021a08f474e40a2047c2f9945314bf` in the Ubuntu/Python 3.14 daemon lifecycle tests. This checkout contains the fixes and focused regressions; a new hosted run must pass after the commit is pushed.

`tools/release_check.py --allow-installed` currently stops because pre-existing `build/` and `dist/` directories are present (timestamps 2026-10-26). They were preserved. Release-check therefore is not recorded as passing. The live model check and a dashboard screenshot were not used as release claims.
