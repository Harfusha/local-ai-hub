# Agent Efficiency and Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add measured provider/cache telemetry and bounded agent workflows without broadening public schemas or enabling mutation by default.

**Architecture:** Existing telemetry remains metadata-only and gains measured numeric provider usage. `LocalAIServices` owns cache-key and repository-result behavior; `CommandBroker` owns deterministic failure extraction and opt-in lint scheduling. MCP and generated prompts expose only existing canonical actions and operational guidance.

**Tech Stack:** Python 3.11, FastMCP, SQLite telemetry, pytest.

**Spec:** `docs/superpowers/specs/2026-09-17-agent-efficiency-observability-design.md`

## Global Constraints

- Preserve public `Literal` action schemas; add no aliases.
- Keep command-policy blocking default `False` and unconditional dangerous-command denial intact.
- Persist no prompt, source, model output, timestamp, provider request ID, or full path in telemetry.
- Keep speculative lint disabled by default and read-only.
- Use full logs only through artifacts; model fallback receives bounded failure excerpts plus opaque artifact ID.

---

### Task 1: Measured provider usage and cache-key preservation

**Files:**
- Modify: `src/local_ai_hub/telemetry.py`, `src/local_ai_hub/services.py`, `src/local_ai_hub/token_accounting.py`
- Test: `tests/test_generation_cache_keys.py`, `tests/test_token_accounting.py`

- [ ] Add failing tests that a provider usage record preserves raw request diagnostics outside telemetry, records only numeric `input_tokens`, `cache_read_tokens`, `output_tokens`, and uses exact prompt text except line endings.
- [ ] Run focused tests; confirm cache key currently normalizes forbidden dynamic fields or lacks cache-read accounting.
- [ ] Replace cache-key normalization with line-ending normalization only. Extend telemetry/event aggregation with non-negative measured cache-read tokens and tool/action/task-kind dimensions.
- [ ] Run focused tests; verify unavailable provider usage produces no fabricated savings.

### Task 2: Navigable enriched repository search

**Files:**
- Modify: `src/local_ai_hub/services.py`, `src/local_ai_hub/repo_tools.py`, `src/local_ai_hub/projection.py`, `src/local_ai_hub/mcp_server.py`
- Test: `tests/test_projection_extra_fields.py`, `tests/test_mcp_agent_routing.py`

- [ ] Add failing tests for `search(include_code=True)` returning bounded context, enclosing symbol, and evidence ID for each hit.
- [ ] Run tests; confirm fields are absent or incomplete.
- [ ] Reuse existing search, symbol lookup, and evidence store to enrich results without a new search engine. Keep `ast_outline` separate.
- [ ] Run focused tests and assert compact projection exposes source fields only when requested.

### Task 3: Safe batch ownership validation

**Files:**
- Modify: `src/local_ai_hub/deterministic.py`, `src/local_ai_hub/repo_tools.py`
- Test: `tests/test_new_capabilities_and_hardening.py`

- [ ] Add failing tests for rejecting an exact replacement overlapping an unowned dirty Git hunk while permitting a clean-file replacement.
- [ ] Run tests; confirm current atomic replacement has no hunk-ownership check.
- [ ] Compute zero-context Git diff ranges before in-memory replacement and reject intersecting target ranges unless a matching active lease belongs to caller.
- [ ] Run batch tests for atomic rollback, ambiguity, syntax, clean target, and dirty-hunk rejection.

### Task 4: Layered command failure distillation

**Files:**
- Modify: `src/local_ai_hub/commands.py`, `src/local_ai_hub/services.py`, `src/local_ai_hub/http_server.py`
- Test: `tests/test_command_unblocked.py`, `tests/test_command_suppression.py`

- [ ] Add failing tests for deterministic location extraction, artifact retention of full bounded log, and model fallback only when parser returns no location.
- [ ] Run tests; identify current output/artifact behavior.
- [ ] Store stdout/stderr artifact before compact response. Return deterministic summary when available; otherwise submit only excerpt and artifact ID through existing local-task path.
- [ ] Run focused tests; verify default command policy remains unblocked and hard deny remains terminal.

### Task 5: Opt-in speculative lint queue

**Files:**
- Modify: `src/local_ai_hub/defaults.toml`, `src/local_ai_hub/config.py`, `src/local_ai_hub/commands.py`, `src/local_ai_hub/http_server.py`, `src/local_ai_hub/mcp_server.py`
- Test: `tests/test_command_suppression.py`, `tests/test_async_jobs.py`

- [ ] Add failing tests for disabled-by-default submission, changed-path filtering, debounce replacement, cancellation, and no auto-fix invocation.
- [ ] Run tests; confirm no speculative lint API exists.
- [ ] Add explicit read-only submission/status/cancel endpoints backed by existing async-job primitives. Cancel prior queued work per root; run lint only after debounce against supplied paths.
- [ ] Run focused tests; verify no command cache or mutation path is used.

### Task 6: Durable-work guidance and polling telemetry

**Files:**
- Modify: `src/local_ai_hub/telemetry.py`, `src/local_ai_hub/generator.py`, `docs/INSTALL_PROMPT.md`, `docs/UPDATE_PROMPT.md`
- Test: `tests/test_agent_state_transport.py`, `tests/test_async_jobs.py`, `tests/test_release_contract.py`

- [ ] Add failing tests for numeric wait telemetry and generated guidance requiring one task contract, checkpoints, and one bounded wait.
- [ ] Run tests; confirm current guidance lacks one of these requirements.
- [ ] Add wait-count/duration fields to telemetry aggregation and synchronize generated install/update prompts with contract/checkpoint/durable-wait guidance.
- [ ] Run focused tests and verify prompt parity.

### Task 7: Integration verification

**Files:**
- Modify: test files only when coverage gaps remain.

- [ ] Run all task-focused tests plus `python tools/release_check.py`, `python -m compileall -q src mcp tools tests`, `python -m pytest -q`, and `python tools/selftest.py`.
- [ ] Review diff, run secret/security scan, and record exact passed commands.
