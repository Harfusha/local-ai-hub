# Telemetry, Reliability, and Cache Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended for this session) to implement this plan task-by-task.

**Goal:** Correct false token savings, make failure/cache telemetry truthful, and improve safe reuse of repeated local work.

**Architecture:** Keep deterministic repository work and local generation reuse as separate telemetry domains. Token accounting accepts only explicit measured signals; HTTP outcomes use endpoint-aware categories; dashboard renders domain-specific cache and failure counters.

**Tech Stack:** Python 3.11+, SQLite telemetry/cache stores, pytest, small embedded dashboard JavaScript.

---

### Task 1: Stop unproven diff/context sizes becoming cloud savings

**Files:**
- Modify: `src/local_ai_hub/token_accounting.py`
- Modify: `src/local_ai_hub/repo_tools.py`
- Test: `tests/test_token_accounting.py`

- [x] Add failing tests proving `original_diff_tokens` and `original_estimated_tokens` remain diagnostics and do not contribute to `gross_cloud_tokens_avoided_est`, while explicit `token_saving.delegated_cloud_context_tokens_avoided_est` still does.
- [x] Run focused accounting tests and confirm the new assertions fail against current behavior.
- [x] Remove generic scanning of counterfactual diff/context fields from savings measurement; retain fields in responses for diagnostics.
- [x] Remove `token_saving.delegated_cloud_context_tokens_avoided_est` from deterministic search results; expose local candidate size under a diagnostic-only field.
- [x] Run focused accounting/repo tests and confirm no double counting.

### Task 2: Expose cache domains separately

**Files:**
- Modify: `src/local_ai_hub/telemetry.py`
- Modify: `src/local_ai_hub/dashboard.py`
- Modify: `src/local_ai_hub/app.py`
- Test: `tests/test_token_accounting.py`
- Test: `tests/test_stuck_preprocessing_and_dashboard_fixes.py`

- [x] Add failing summary tests for generation-cache hits, repo-result cache hits, command-cache hits, and single-flight reuse as separate counters/rates.
- [x] Run focused tests and confirm failure because summary currently queries only inference rows.
- [x] Add bounded SQL aggregation for cache-layer/domain counters without counting unrelated HTTP events as generation hits.
- [x] Render the headline as generation-cache hit rate and show domain totals beside it; preserve current fields for API compatibility.
- [x] Run focused dashboard/telemetry tests.

### Task 3: Classify compatibility noise and command failures

**Files:**
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `src/local_ai_hub/telemetry.py`
- Modify: `src/local_ai_hub/dashboard.py`
- Test: `tests/test_http_telemetry_outcomes.py`
- Test: `tests/test_stuck_preprocessing_and_dashboard_fixes.py`

- [x] Add failing tests for legacy versioned-endpoint 404 compatibility events, policy blocks, command timeouts, and non-zero command exits.
- [x] Run focused tests and verify expected red failures.
- [x] Add endpoint-aware compatibility classification; keep 404s visible but exclude them from operational failure rate.
- [x] Add separate HTTP counters for operational, compatibility, and policy outcomes; keep policy blocks non-failures.
- [x] Run focused HTTP telemetry tests.

### Task 4: Improve generation-cache reuse without unsafe cross-context reuse

**Files:**
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/cache.py` only if required by tests
- Test: `tests/test_services.py` or the existing service/cache test module

- [x] Add a failing test for repeated identical non-conversational generation returning an exact cache hit, plus a test that changed context/model/options does not hit.
- [x] Run the focused cache tests and confirm the hit assertion fails or is absent.
- [x] Normalize only transport/presentation-stable inputs used in generation keys; keep model, system, execution profile, context fingerprint, and app version in scope.
- [x] Preserve `use_cache=False` for conversations and never cache fallback-model output as requested-model output.
- [x] Run focused cache tests and inspect cache-layer telemetry.

### Task 5: Verify integrated behavior and review diff

**Files:**
- Modify: documentation only if metric names/semantics changed.

- [x] Run the focused suites through `local_ai_command`.
- [x] Run `python tools/release_check.py`, `python -m compileall -q src mcp tools tests`, `python -m pytest -q`, and `python tools/selftest.py` through the command broker.
- [x] Query live telemetry once and confirm false diff savings no longer dominate, compatibility 404s are separated, and cache domains are visible.
- [x] Review unified diff and ensure unrelated existing user changes remain untouched.
