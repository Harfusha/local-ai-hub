# T13 root-current audit update — 2026-10-01

## Scope and ownership

- Current-root source was copied into isolated overlay `handoff/root-current-operational-audit-20261001`.
- Production root `C:\Users\Adam\.local-ai-hub` remained read-only. No product code changed there.
- Root-current tests were run in the isolated overlay. Patch below is test-only and is for T20 integration review.
- T13 must not edit `async_jobs.py`; executor-boundary failures remain with async owner.

## Fresh receipts

- Seven scoped root-current suites: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_operational_mode.py tests/test_operational_mode_http_gate.py tests/test_mcp_operational_mode_dispatch.py tests/test_mcp_agent_routing.py tests/test_preprocess_operational_mode.py tests/test_hubctl_mode.py tests/test_dashboard_operational_surfaces.py` — **110 passed in 6.12s**.
- Executor-boundary selector: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_async_operational_mode.py::test_mode_change_at_executor_boundary_prevents_start` — **2 failed in 0.43s**. Both `gaming-reason` and `maintenance-speculative_lint` expected `cancelled`, got `running`. This is async owner scope; no T13 edit.
- Earlier exact T02 delayed-submit selector in this isolated overlay: **1 passed in 0.14s** (see parent audit record).
- Scoped test patch dry-run against current root: `git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub\handoff\T13-rootcurrent-hubctl-tests-20261001.patch` — passed.
- Current root `src/local_ai_hub/operational_mode.py` SHA-256: `50FA2F56E0B0FDECED08EA1603C78D81DB2E4451BDEFA4E1D6D219D0FD60E8F9`.
- Current root `tests/test_hubctl_mode.py` is untracked (`??`) at audit time. It was read and apply-checked only; not changed.

## Findings

- Process/file-lock and Windows replace retry coverage passes in `test_operational_mode.py`.
- HTTP route requires authorization; mode-control gate, loopback restrictions, MCP dispatch, dashboard reporting, and preprocess pause behavior pass scoped suites.
- Ollama unload uses a bounded shared deadline, checks cancellation, inventories loaded Ollama and llama.cpp models, attempts requested unloads, then verifies post-unload inventory. Result separates loaded-set verification from physical VRAM reclamation (`physical_vram_reclaimed: false`).
- Offline gaming persists the requested mode but cannot prove runtime unload or accelerator release. CLI exits `1` and reports incomplete transition. Patch updates mock fixture and offline gaming expectations accordingly; resume/maintenance remain exit `0`.
- Unrelated incomplete-overlay failures in legacy T18 and unlinked-operation suites remain excluded as previously recorded.

## Handoff patch

- `T13-rootcurrent-hubctl-tests-20261001.patch`
- SHA-256: `0293ED924E804170585D6E8B1D081AE0B8C242DC8E4F9F44CB6E0FE76D75FA44`
- Scope: `tests/test_hubctl_mode.py` only.
