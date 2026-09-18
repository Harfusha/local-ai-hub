# Local-model routing enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make semantic work visibly and measurably hand off to `local_ai_task` after deterministic evidence, while keeping cloud-agent coordination and verification intact.

**Architecture:** Add a pure routing classifier that marks repository evidence responses with a structured semantic-handoff contract. Integrate it at the MCP instrumentation boundary and record bounded recommendation/use/bypass aggregates. Strengthen generated policy, MCP descriptions, and canonical install/update prompts so the cloud agent must perform the handoff or report a bounded bypass.

**Tech Stack:** Python 3.11+, FastMCP wrappers, SQLite aggregate telemetry, pytest, generated Markdown prompts.

---

### Task 1: Add pure semantic-handoff routing contract

**Files:**
- Create: `src/local_ai_hub/routing.py`
- Test: `tests/test_routing.py`

- [ ] **Step 1: Write the failing tests**

```python
from local_ai_hub.routing import semantic_handoff_hint


def test_repository_evidence_requires_local_semantic_handoff():
    hint = semantic_handoff_hint("local_ai_repo", "search", local_tasks_enabled=True)

    assert hint == {
        "required": True,
        "tool": "local_ai_task",
        "actions": ["delegate", "explore", "reason", "review", "second_opinion", "compress"],
        "bypass_tool": "local_ai_status",
        "bypass_action": "bypassed",
    }


def test_disabled_local_tasks_do_not_claim_a_handoff():
    assert semantic_handoff_hint("local_ai_repo", "search", local_tasks_enabled=False) is None


def test_exact_and_validation_tools_have_no_semantic_handoff():
    assert semantic_handoff_hint("local_ai_artifact", "get", local_tasks_enabled=True) is None
    assert semantic_handoff_hint("local_ai_command", "run", local_tasks_enabled=True) is None
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run: `python -m pytest -q tests/test_routing.py`

Expected: collection fails because `local_ai_hub.routing` does not exist.

- [ ] **Step 3: Implement the minimal classifier**

Create a frozen tuple of semantic actions and return the exact bounded dictionary above only for `local_ai_repo` evidence actions (`search`, `code_index`, `context`, `deterministic`, `symbols`, `callers`, `dead_code`, `impact`, `refactor_impact`, `affected_tests`, `dependency_slice`, `structural_search`, `ast_outline`, `test_matrix`, `complexity`, `profile`, and `map`). Return `None` for all other tools/actions or when local tasks are disabled. Keep the function free of prompts, source text, paths, and model calls.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest -q tests/test_routing.py`

Expected: all routing tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_routing.py src/local_ai_hub/routing.py
git commit -m "feat: define semantic local-model handoff contract"
```

### Task 2: Attach handoff and adoption telemetry at MCP boundary

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py` in `_instrumented_tool`, `_record_adoption`, and status/report helpers
- Modify: `src/local_ai_hub/adoption_metrics.py` in outcome/report aggregation
- Test: `tests/test_mcp_agent_routing.py`
- Test: `tests/test_adoption_metrics.py`

- [ ] **Step 1: Write failing integration tests**

Add tests that invoke the instrumented local repository path with a successful bounded response and assert a `routing.semantic_handoff` object is present, while exact artifact and command responses remain unchanged. Add an adoption-store test asserting the report contains:

```python
assert report["routing_adoption"] == {
    "local_recommended": 1,
    "local_used": 2,
    "bypassed": 1,
    "fallback_used": 0,
}
```

Use only aggregate tool/action/outcome values; never include prompt, source, content, secret, token, or path values.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest -q tests/test_mcp_agent_routing.py tests/test_adoption_metrics.py`

Expected: new assertions fail because the routing field and `routing_adoption` report are absent.

- [ ] **Step 3: Add structured handoff**

In `_instrumented_tool`, after `pop_accounting` and before returning, call `semantic_handoff_hint` with the tool name and action. If the result is non-`None` and the cleaned result is a dictionary, attach it under `result["routing"]["semantic_handoff"]` without replacing existing fields. Record one aggregate `recommended` event for the semantic handoff. Do not attach hints to failed, unsupported, artifact, command, mutation, security, or local-task responses.

- [ ] **Step 4: Add aggregate routing report**

Extend the bounded adoption store with `recommended` and `fallback` outcomes. Preserve existing `used`, `bypassed`, `blocked`, and `failed` totals. Add `routing_adoption` derived only from aggregate rows: recommendation count, successful `local_ai_task` count, bypass count, and fallback count. Treat an explicit `fallback_used` result as fallback; otherwise preserve current blocked/failed classification. Keep SQLite state disposable and retention bounded.

- [ ] **Step 5: Run focused tests and verify green**

Run: `python -m pytest -q tests/test_mcp_agent_routing.py tests/test_adoption_metrics.py`

Expected: focused tests pass with no telemetry payload leakage.

- [ ] **Step 6: Commit**

```bash
git add src/local_ai_hub/mcp_server.py src/local_ai_hub/adoption_metrics.py tests/test_mcp_agent_routing.py tests/test_adoption_metrics.py
git commit -m "feat: expose semantic handoff and routing adoption metrics"
```

### Task 3: Enforce agent-facing policy and synchronize prompts

**Files:**
- Modify: `src/local_ai_hub/generator.py` in `generate_global_policy`
- Modify: `src/local_ai_hub/mcp_server.py` in `_desc_task` and `_desc_repo`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`
- Test: `tests/test_generator.py`
- Test: `tests/test_mcp_agent_routing.py`

- [ ] **Step 1: Write failing policy tests**

Assert generated policy and MCP descriptions contain all of these concepts:

```python
assert "semantic handoff is mandatory" in policy.lower()
assert "before cloud reasoning" in policy.lower()
assert "report a bypass" in policy.lower()
assert "local_ai_task" in task_description
assert "semantic handoff" in repo_description
```

Also assert disabled local-task configurations do not claim mandatory local execution.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest -q tests/test_generator.py tests/test_mcp_agent_routing.py`

Expected: new routing-policy assertions fail against the current advisory wording.

- [ ] **Step 3: Replace advisory wording with explicit routing contract**

Generated policy must state:

```text
Semantic handoff is mandatory: after deterministic/indexed evidence, any planning, interpretation, synthesis, generation, review, compression, or second-opinion work must call local_ai_task before cloud reasoning. The cloud agent must integrate the bounded local result, not redo that semantic work. If local inference is unavailable or intentionally excluded by a permitted boundary, report the bypass through local_ai_status(adoption_signal="bypassed", target_tool="local_ai_task", target_action="reason") with no prompt/source payload.
```

MCP descriptions must repeat the same boundary in compact form. Preserve existing exceptions for architecture, security, mutations, open-ended coding, exact evidence, and verification.

- [ ] **Step 4: Synchronize canonical prompts**

Insert the same routing contract into `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md`, using the configured action names and without adding a new public MCP tool. Keep model-tier wording consistent with generated policy.

- [ ] **Step 5: Run focused tests and policy consistency checks**

Run: `python -m pytest -q tests/test_generator.py tests/test_mcp_agent_routing.py tests/test_feature_surface_parity.py`

Expected: all pass. Then run `rg -n "Semantic handoff is mandatory|before cloud reasoning" docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md src/local_ai_hub/generator.py` and confirm both prompts and generator contain the contract.

- [ ] **Step 6: Commit**

```bash
git add src/local_ai_hub/generator.py src/local_ai_hub/mcp_server.py docs/INSTALL_PROMPT.md docs/UPDATE_PROMPT.md tests/test_generator.py tests/test_mcp_agent_routing.py
git commit -m "feat: require local semantic handoff before cloud reasoning"
```

### Task 4: Full verification and review

**Files:**
- Review: all files changed by Tasks 1–3

- [ ] **Step 1: Run repository validation through the command broker**

Run via `local_ai_command`: `python -m pytest -q --tb=short`.

Expected: exit status 0 and zero failed tests.

- [ ] **Step 2: Run release checks**

Run via `local_ai_command`: `python tools/release_check.py` and `python -m compileall -q src mcp tools tests`.

Expected: both commands pass.

- [ ] **Step 3: Review impact and security**

Run `local_ai_repo(action="review_diff")` and `local_ai_repo(action="security_audit")` for the final diff. Confirm routing metadata stays aggregate-only and no prompt/source/path data enters adoption telemetry.

- [ ] **Step 4: Check final state**

Run `git diff --check` and `git status --short`. Confirm only intended implementation, tests, synchronized prompts, and plan/spec commits exist.
