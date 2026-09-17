# Context Budget Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce compact, artifact-backed MCP responses with measurable reuse so repeated Hub, search, command, validation, and edit context stops dominating Codex input tokens.

**Architecture:** Keep the eight-tool MCP surface. Add a shared response-budget layer after `AgentProjector` and `compact_result`; it preserves decision-grade fields, applies an aggregate token cap, and returns artifact/evidence pointers for omitted detail. Add optional `max_response_tokens`, `response_profile`, and `reuse_key` arguments to existing tools with safe defaults, then record raw/projected/saved token estimates and operation categories in metadata-only telemetry. Generate one short context-economy contract into all agent instructions instead of repeating long prose.

**Tech Stack:** Python 3.11+, FastMCP, TOML configuration, pytest, existing artifact/evidence store, existing token accounting and generator.

---

### Task 1: Add the shared response-budget primitive

**Files:**
- Create: `src/local_ai_hub/response_budget.py`
- Modify: `src/local_ai_hub/compact.py`
- Test: `tests/test_response_budget.py`

- [ ] **Step 1: Write failing tests for aggregate limits and priority fields**

Add tests asserting that a result with many `results`, `evidence`, and long text is reduced below the requested estimate, while `success`, `error`, `status`, `artifact_id`, `evidence_ids`, `changed_paths`, and `summary` survive. Assert that a small result is byte-for-byte equivalent and that truncation metadata is deterministic.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m pytest -q tests/test_response_budget.py`

Expected: collection or assertion failure because the budget module does not exist.

- [ ] **Step 3: Implement deterministic budget projection**

Implement `budget_response(value, max_tokens, profile, artifact_backed=True)` using existing `json_tokens` and `compact_result`. Use this reduction order: nested lists/results, evidence count, low-priority keys, text fields, then a pointer-only envelope. The envelope contains `success`, status/error fields, IDs, counts, a bounded summary, and `response_budget={requested_tokens, returned_tokens, truncated, omitted_items}`. Never include raw source or log text in the envelope.

Extend `compact_result` with a bounded `max_items` parameter so aggregate reduction is not limited to the current fixed 50-item list cap.

- [ ] **Step 4: Run focused tests and verify pass**

Run: `python -m pytest -q tests/test_response_budget.py tests/test_ast_compaction.py`

Expected: PASS.

### Task 2: Wire budgets and reuse into the MCP boundary

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `defaults.toml`
- Test: `tests/test_mcp_response_budget.py`
- Test: `tests/test_mcp_agent_routing.py`

- [ ] **Step 1: Add failing MCP boundary tests**

Test `_compact` with the configured default and per-tool budgets. Test that `max_response_tokens` overrides the default, `response_profile="minimal"` selects the smaller profile, and a repeated `reuse_key` with an unchanged result returns a compact reuse envelope containing IDs and summary.

- [ ] **Step 2: Implement configuration and context-local options**

Add `[mcp.response_budget]` defaults: enabled, default tokens, per-tool token budgets, minimal/compact/standard profiles, and reuse TTL. Add `max_response_tokens`, `response_profile`, and `reuse_key` to the existing MCP function signatures. Keep `0`/empty values backward-compatible by selecting the configured profile.

- [ ] **Step 3: Apply projection order at `_compact`**

Keep accounting before stripping private metadata. Apply `AgentProjector`, `compact_result`, then `budget_response`; pass the final projected value to `account_projection`. Store only a bounded reuse fingerprint and pointer metadata in an in-process LRU map; never store prompts, source text, or full output.

- [ ] **Step 4: Run MCP tests**

Run: `python -m pytest -q tests/test_mcp_response_budget.py tests/test_mcp_agent_routing.py tests/test_work_orchestrator.py`

Expected: PASS.

### Task 3: Extend metadata-only token attribution

**Files:**
- Modify: `src/local_ai_hub/token_accounting.py`
- Modify: `src/local_ai_hub/mcp_server.py`
- Test: `tests/test_token_accounting.py`
- Test: `tests/test_response_budget.py`

- [ ] **Step 1: Add failing attribution tests**

Assert that finalized accounting includes operation category, raw response estimate, projected response estimate, saved response estimate, budget status, cache outcome, and projection reason. Assert that no prompt, source text, secret, or full path is serialized into the event.

- [ ] **Step 2: Implement safe attribution fields**

Derive category from tool name and action (`search`, `command`, `validation`, `edit`, `artifact`, `coordination`, `task`, `status`, `other`). Add raw/projected/saved estimates and bounded flags from the response envelope. Preserve existing conservative max-not-sum savings behavior.

- [ ] **Step 3: Run accounting tests**

Run: `python -m pytest -q tests/test_token_accounting.py tests/test_response_budget.py`

Expected: PASS.

### Task 4: Make command, search, and artifact responses decision-grade

**Files:**
- Modify: `src/local_ai_hub/projection.py`
- Modify: `src/local_ai_hub/commands.py`
- Modify: `defaults.toml`
- Test: `tests/test_command_terse_output.py`
- Test: `tests/test_projection_extra_fields.py`
- Test: `tests/test_context_budget.py`

- [ ] **Step 1: Add regression cases for large command/search payloads**

Cover long stdout/stderr, 50+ search results, nested repo context, and artifact fetches. Assert that summaries and failure diagnostics remain available while detail moves behind artifact/evidence IDs.

- [ ] **Step 2: Implement profiles and safe defaults**

Set compact command inline output to a bounded value aligned with the response budget. Ensure `local_ai_artifact` remains the explicit exact-content path. Keep debug/explicit extra fields available for diagnostics, but do not let them bypass aggregate budgeting unless `response_profile="debug"` is explicitly requested.

- [ ] **Step 3: Run focused tests**

Run: `python -m pytest -q tests/test_command_terse_output.py tests/test_projection_extra_fields.py tests/test_context_budget.py`

Expected: PASS.

### Task 5: Shorten and synchronize generated agent guidance

**Files:**
- Modify: `src/local_ai_hub/generator.py`
- Modify: `skills/local-ai-orchestrator/SKILL.md`
- Modify: `docs/MCP_AND_AGENTS.md`
- Modify: `docs/TOKEN_ECONOMY.md`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`
- Modify: the repository-managed `token-economizer/SKILL.md` only if applicable; otherwise update the generated policy source instead.
- Test: `tests/test_model_policy_repetition.py`
- Test: `tests/test_surface_and_packaging.py`

- [ ] **Step 1: Add generator tests for the context-economy contract**

Assert that every generated policy contains the same short rules: bounded response budget, reuse keys/cache hits, artifact slices for exact detail, command summaries, and no repeated identical queries. Assert that generated MCP descriptions document the new optional fields.

- [ ] **Step 2: Implement one canonical generated contract**

Add a generator helper that emits the contract once into skill references and global policy blocks. Keep installation/update prompts synchronized with the same wording and defaults. Remove duplicated long paragraphs only where the generated contract covers them.

- [ ] **Step 3: Regenerate checked-in artifacts and run packaging tests**

Run the repository generator command used by existing packaging tests, then:

`python -m pytest -q tests/test_model_policy_repetition.py tests/test_surface_and_packaging.py`

Expected: PASS with no stale generated policy.

### Task 6: Validate, benchmark, and close the Agent OS task

**Files:**
- Modify: `docs/TOKEN_ECONOMY.md` with before/after measurement procedure and expected attribution fields.
- Test: existing full suite.

- [ ] **Step 1: Run indexed impact/review before broad validation**

Use `local_ai_repo(action="impact")` for changed source symbols and `local_ai_repo(action="review_diff")` for the final diff. Fix any findings before full validation.

- [ ] **Step 2: Run bounded validation through the command broker**

Run, in order, through `local_ai_command`: release check, compileall, focused tests, full pytest, and selftest. Reuse cached results; do not duplicate an `in_progress` command.

- [ ] **Step 3: Replay the 24-hour token classification**

Compare raw response estimates, projected response estimates, reuse-only responses, and category totals. Report actual reductions separately for Hub, shell/CLI, search, validation, and edits. Do not claim a reduction from estimates without replay evidence.

- [ ] **Step 4: Attach validation receipts and complete the task**

Use `local_ai_coord(action="verify_receipt")` for passing criteria, then `task_complete` only after all acceptance criteria and validation commands have receipts.

## Self-review

- Spec coverage: MCP budgets, artifact/reuse pointers, telemetry, skills, MCP schemas, defaults, tests, and 24-hour replay are covered by Tasks 1–6.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation step appears in the plan.
- Type consistency: public options are named `max_response_tokens`, `response_profile`, and `reuse_key` throughout; existing `max_output_tokens` remains the `local_ai_work` handoff budget.
- Compatibility: default values preserve existing calls; debug and explicit artifact retrieval remain available; no new public MCP tool is added.
