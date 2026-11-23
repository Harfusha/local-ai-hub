# Antigravity Policy Size Implementation Plan

> **For agentic workers:** Native implementation in the current session; keep each step checkable and preserve the shared checkout.

**Goal:** Keep combined generated Antigravity policies at or below 23,900 UTF-8 bytes for configured and high profiles while retaining the full tool contract.

**Architecture:** Keep the complete tenant-free scope contract in the generated `local-ai-orchestrator` skill, which setup installs and activates. Keep the global generated policy concise and point to that skill for the complete details. Synchronize the managed policy blocks in both canonical prompts without changing their surrounding user edits.

**Tech Stack:** Python policy generation, Markdown prompt blocks, pytest.

**Spec:** `docs/FINAL_COMPLETION_PLAN.md`; `docs/UPDATE_PROMPT.md` generated-instruction size requirement.

## Global Constraints

- Combined generated Antigravity policy size must stay below 23,900 UTF-8 bytes; do not raise the cap.
- Preserve all scope, authorization, privacy, receipt and fallback rules in the always-loaded skill.
- Preserve user edits outside the managed generated-policy blocks in `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md`.
- Do not download models, train, restart services/clients, enable telemetry, or alter GPU leases.
- No commit, reset, stash or cleanup.

## Review Focus

- The full contract must remain available when the skill is loaded; the global summary must require that skill before repository work.
- Both configured/default and `high` profiles must pass the same byte cap.
- Prompt blocks must match generator output while all surrounding prompt text stays intact.
- The unsupported-action rule must not reintroduce the retired `native_fallback_allowed` signal.

---

### Task 1: Compact global policy, preserve full skill contract

**Files:** `src/local_ai_hub/generator.py`; `tests/test_generator.py`; existing generated policy tests.

- [x] Confirm failing default and `high` cap tests before editing.
- [x] Move the repeated detailed scope text out of the global block only; retain it in the generated always-loaded skill and include a concise pointer plus core constraints in the global block.
- [x] Keep the exact 23,900-byte guard.
- [x] Run the existing default and high-profile cap tests; both must pass.

### Task 2: Synchronize canonical prompt blocks

**Files:** `docs/INSTALL_PROMPT.md`; `docs/UPDATE_PROMPT.md`; `tests/test_setup.py`; `tests/test_token_economy_tools.py`.

- [x] Keep the user's host-native/no-action and fallback additions in generated policy text.
- [x] Replace only the managed policy blocks with generator output; preserve all text outside those blocks.
- [x] Update any fallback-contract assertion that still requires the retired `native_fallback_allowed` token when no Hub action exists.
- [x] Run prompt-parity and token-economy tests.

### Task 3: Final bounded verification

- [x] Run `tests/test_t19_install_contracts.py`, `tests/test_generator.py`, `tests/test_setup.py`, `tests/test_token_economy_tools.py`, and `tests/test_t19_prompt_profile_parity.py`.
- [x] Run `python tools/release_check.py --allow-installed` and `python -m compileall -q src tools tests`.
- [x] Report any remaining unrelated baseline failures by exact test name; do not claim client, runtime, or release acceptance.

Verification 2026-11-18: targeted set (plus sync and fallback policy tests) **123 passed in 49.53s**; default/high generated policy cap cases both passed. Combined generated policy sizes: default **3,730 B**, high **3,739 B** (23,900 B cap unchanged). `sync_prompt_policies.py --check`, `release_check.py --allow-installed`, `compileall` passed. Client/runtime acceptance not run.

Final fallback clarification: the generated skill retains `native_fallback_allowed=true` only for Hub-classified unknown commands with exact native-tool authorization. Missing live-schema actions require no Hub call or signal. Fresh focused skill, setup and default/high cap checks → **4 passed**; generator pyflakes, prompt parity and scoped diff check passed.

Current-source recheck 2026-11-19: the five policy files passed **119 tests** in 51.79s; prompt block sync and `release_check.py --allow-installed` passed. Combined generated policy sizes are **3,709 B** (default) and **3,863 B** (high), under the unchanged **23,900 B** cap. The active user skill's fallback clauses were synchronized without replacing its user-specific model routing; its SHA-256 is `afad8d8f81db6d798a2abd1498bbcbc4e3be72137adf2f7292655f16f03c2f0f`. Client handshake and runtime acceptance remain unverified.

Final focused recheck 2026-11-19: freshly recomputed combined generated-policy sizes are 3,709 B (default) and 3,863 B (high), under the unchanged 23,900 B cap. sync_prompt_policies.py --check passed; generator cap, prompt-source parity and profile-routing checks passed 6/6. Restored the compact Local model policy: summary required by profile-parity tests; detailed scope rules remain in the always-loaded skill. No client restart, handshake or live dashboard acceptance was run.
