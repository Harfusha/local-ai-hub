# Agent Adoption Nudges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase voluntary Local AI Hub use by making tool selection and lifecycle timing obvious to agents, without runtime enforcement.

**Architecture:** Keep `tools/setup.py::GLOBAL_POLICY` as the single shared policy source. Add a front-loaded trigger card and three lifecycle recipes, mirror the guidance in the orchestrator skill, and add `Use when`/`Skip when` cues to all seven MCP tools. Generated manifests remain compatibility artifacts; no new MCP tool, automatic routing, or direct external MCP server is added.

**Tech Stack:** Python 3.11, Markdown, MCP Python SDK, pytest, existing setup/manifests.

---

### Task 1: Add failing adoption-policy tests

**Files:**
- Modify: `tests/test_v1_5_reliability.py:642-654`
- Reference: `tools/setup.py:23-42`
- Reference: `skills/local-ai-orchestrator/SKILL.md:20-50`

- [ ] **Step 1: Add a test for the front-loaded trigger card and recipes**

Add this test beside `test_agent_policy_is_consistent_and_has_stop_reuse_protocol`:

```python
def test_agent_policy_has_actionable_adoption_triggers_and_recipes():
    spec = importlib.util.spec_from_file_location("local_ai_hub_setup_adoption", ROOT / "tools" / "setup.py")
    assert spec and spec.loader
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    policy = setup.GLOBAL_POLICY
    expected = (
        "Trigger map:",
        "repository facts/files/symbols: `local_ai_repo`",
        "tests/lint/typecheck/build: `local_ai_command`",
        "exact source/evidence text: `local_ai_artifact`",
        "shared findings or overlapping edits: `local_ai_coord`",
        "semantic retrieval after indexed paths are insufficient: `local_ai_rag`",
        "bounded local generation or second opinion: `local_ai_task`",
        "Recipe — Explore:",
        "Recipe — Change:",
        "Recipe — Validate:",
        "guidance, not gates",
    )
    for phrase in expected:
        assert phrase in policy

    skill = (ROOT / "skills" / "local-ai-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
    for phrase in expected:
        assert phrase in skill
```

- [ ] **Step 2: Run the new test and verify the expected failure**

Run through the command broker first:

```text
local_ai_command(action="run", cwd=".", command="python -m pytest tests/test_v1_5_reliability.py::test_agent_policy_has_actionable_adoption_triggers_and_recipes -q", timeout=120)
```

Expected: `FAIL` because the current policy and skill do not contain the new trigger-card phrases.

### Task 2: Implement shared policy nudges

**Files:**
- Modify: `tools/setup.py:23-42`
- Modify: `skills/local-ai-orchestrator/SKILL.md:16-50`
- Modify: `generated/agent-policy.md:1-19`

- [ ] **Step 1: Add the trigger card to `GLOBAL_POLICY`**

Place this block immediately after the policy begin marker and before the routing hierarchy:

```text
Trigger map:
- repository facts/files/symbols: `local_ai_repo`
- tests/lint/typecheck/build: `local_ai_command`
- exact source/evidence text: `local_ai_artifact`
- shared findings or overlapping edits: `local_ai_coord`
- semantic retrieval after indexed paths are insufficient: `local_ai_rag`
- bounded local generation or second opinion: `local_ai_task`
```

Keep existing cheapest-first routing, fallback rules, safety restrictions, and model defaults unchanged below it.

- [ ] **Step 2: Add the three lifecycle recipes to `GLOBAL_POLICY`**

Add this block after the trigger card:

```text
Recipes (guidance, not gates):
- Recipe — Explore: preprocess once, use the cheapest repository action, fetch only required evidence slices.
- Recipe — Change: gather indexed evidence, use `local_ai_repo(action="solve")` before edits, claim `local_ai_coord` leases for overlapping paths, then run indexed impact/review before validation.
- Recipe — Validate: route repeatable commands through `local_ai_command`, reuse cached results, use `review_diff` or `security_audit` when relevant.
```

Retain the current one-bounded-fallback rule and explicitly say a recipe step can be skipped when irrelevant to the task.

- [ ] **Step 3: Mirror identical adoption guidance in the skill and generated policy**

Copy the same trigger card and recipes into `skills/local-ai-orchestrator/SKILL.md` and `generated/agent-policy.md`, preserving their existing format. Do not add host-specific enforcement language.

- [ ] **Step 4: Run policy tests**

Run through `local_ai_command`:

```text
python -m pytest tests/test_v1_5_reliability.py::test_agent_policy_has_actionable_adoption_triggers_and_recipes tests/test_v1_5_reliability.py::test_agent_policy_is_consistent_and_has_stop_reuse_protocol -q
```

Expected: `2 passed`.

### Task 3: Make MCP tool descriptions actionable

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:86-87,156-157,223-224,321-322,344-345,372-373,397-398`
- Modify: `tests/test_v1_5_reliability.py` (new focused test)

- [ ] **Step 1: Add a failing discoverability test**

Add this test, using the source file as the stable contract for MCP descriptions:

```python
def test_mcp_tools_have_use_when_and_skip_when_cues():
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    for tool in (
        "local_ai_status", "local_ai_task", "local_ai_repo", "local_ai_rag",
        "local_ai_command", "local_ai_coord", "local_ai_artifact",
    ):
        start = source.index(f"def {tool}(")
        end = source.find("\n\n@mcp.tool()", start)
        block = source[start:] if end < 0 else source[start:end]
        assert "Use when:" in block, tool
        assert "Skip when:" in block, tool
```

- [ ] **Step 2: Run the test and verify it fails for the existing descriptions**

Run:

```text
python -m pytest tests/test_v1_5_reliability.py::test_mcp_tools_have_use_when_and_skip_when_cues -q
```

Expected: `FAIL` because current docstrings lack both cues.

- [ ] **Step 3: Update each MCP docstring with concise cues**

Append two lines to each existing docstring without changing function signatures or action enums:

```text
Use when: choose this tool for the bounded task family named by its actions.
Skip when: the task is outside that family or a cheaper sufficient Hub path already answered it.
```

Replace the generic wording with tool-specific cues: status for one bounded health/cache check, task for local-model work, repo for repository facts and lifecycle actions, RAG for fallback semantic retrieval, command for repeatable commands, coord for shared state, and artifact for exact evidence slices.

- [ ] **Step 4: Run the discoverability tests**

Run:

```text
python -m pytest tests/test_v1_5_reliability.py::test_mcp_tools_have_use_when_and_skip_when_cues tests/test_v1_5_reliability.py::test_agent_policy_has_actionable_adoption_triggers_and_recipes -q
```

Expected: `2 passed`.

### Task 4: Verify generated configuration and compatibility

**Files:**
- Modify: `tests/test_v1_5_reliability.py:203-225`
- Reference: `tools/setup.py:326-386`
- Reference: `generated/mcp-servers.json`

- [ ] **Step 1: Extend setup coverage**

In `test_setup_supports_explicit_generic_mcp_config_paths`, after existing JSON assertions, add:

```python
assert (install / "generated" / "agent-policy.md").read_text(encoding="utf-8") == setup.GLOBAL_POLICY + "\n"
generated = json.loads((install / "generated" / "mcp-servers.json").read_text(encoding="utf-8"))
assert generated["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT_PROFILE"] == "generic"
assert generated["mcpServers"]["local-ai"]["args"] == ["-m", "local_ai_hub.mcp_server"]
```

Keep existing unrelated-config and VS Code stdio assertions.

- [ ] **Step 2: Run focused setup tests**

Run through `local_ai_command`:

```text
python -m pytest tests/test_v1_5_reliability.py::test_setup_supports_explicit_generic_mcp_config_paths tests/test_v1_5_reliability.py::test_agent_policy_is_consistent_and_has_stop_reuse_protocol -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run complete validation**

Route each command through `local_ai_command` and reuse a fresh result when available:

```text
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```

Expected: compile succeeds, pytest has zero failures, selftest reports success. If the command broker reports `in_progress=true`, do not launch a duplicate command.

- [ ] **Step 4: Review the final diff and scope**

Confirm only policy/skill/generated guidance, MCP descriptions, tests, and the approved plan/spec changed. Confirm no runtime gate, model-routing change, telemetry change, direct Serena/CodeGraph default, or unrelated host configuration mutation was introduced.

This repository is currently not a Git worktree, so record verification in the task result instead of creating a commit.
