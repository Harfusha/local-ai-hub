# Agent Routing Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the main agent the orchestrator, use AGY for fuzzy delegated work, and make Local AI Hub the default worker for precise bounded microtasks across Codex and Gemini.

**Architecture:** Keep seven top-level MCP tools for compatibility. Add explicit action enums, action-grouped descriptions, and concise invalid-action guidance in the MCP server. Strengthen the shared policy and workflows with a tier-selection contract and lifecycle recipes, then install the resulting skill/policy/MCP configuration into the current Codex and Gemini global locations without replacing unrelated settings.

**Tech Stack:** Python 3.11, MCP Python SDK, TOML/JSON configuration, Markdown skills, pytest.

---

### Task 1: Make MCP actions discoverable and self-describing

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: compatibility `mcp/local_ai_mcp.py`
- Test: `tests/test_mcp_agent_routing.py`

- [ ] **Step 1: Write failing tests**

Add tests asserting that the seven public functions expose typed action literals, descriptions containing the main-agent/AGY/Hub hierarchy, and valid-action guidance for unknown actions.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `python -m pytest tests/test_mcp_agent_routing.py -q`

Expected: FAIL because current action parameters are plain `str` and descriptions do not contain the routing contract.

- [ ] **Step 3: Implement minimal MCP contract**

Import `Literal`, define canonical action literal aliases, annotate `action`, `detail`, and `scope`, rewrite MCP docstrings with action groups and tier boundaries, and return a concise valid-action list for invalid actions while preserving existing aliases and behavior.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run: `python -m pytest tests/test_mcp_agent_routing.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: clarify local hub action routing`

### Task 2: Strengthen shared policy and workflow guidance

**Files:**
- Modify: `tools/setup.py`
- Modify: `skills/local-ai-orchestrator/SKILL.md`
- Modify: `skills/local-ai-orchestrator/references/tools.md`
- Modify: `skills/local-ai-orchestrator/references/workflows.md`
- Modify: `README.md`
- Modify: `docs/MCP_AND_AGENTS.md`
- Test: `tests/test_mcp_agent_routing.py`

- [ ] **Step 1: Add failing policy assertions**

Add tests requiring policy text to state that the main agent owns planning/integration, AGY handles fuzzy delegation, Local AI Hub handles bounded work, and post-edit workflows recommend impact/review/validation.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `python -m pytest tests/test_mcp_agent_routing.py -q`

Expected: FAIL against the current policy text.

- [ ] **Step 3: Implement policy and workflow updates**

Update the source policy in `tools/setup.py`, then mirror the routing contract in the repository skill and references. Add lifecycle recipes for discovery, pre-edit risk, implementation, post-edit review, validation, and handoff. Mark `local_ai_command` as command-only, `local_ai_task` as bounded local-model work, and AGY as the fuzzy-delegation tier.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run: `python -m pytest tests/test_mcp_agent_routing.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `docs: define agent and local worker hierarchy`

### Task 3: Cover installer and generated manifests

**Files:**
- Modify: `tools/setup.py`
- Modify: `generated/mcp-servers.json`
- Test: `tests/test_v1_5_reliability.py`

- [ ] **Step 1: Add failing installer assertions**

Extend setup tests to assert Codex and Gemini entries use the correct agent profile, preserve unrelated config, and generated policy/manifests contain the new hierarchy.

- [ ] **Step 2: Run targeted tests and verify RED**

Run: `python -m pytest tests/test_v1_5_reliability.py -q`

Expected: FAIL until generated policy/config expectations are updated.

- [ ] **Step 3: Implement installer changes**

Keep managed-block merging behavior. Ensure generated policy is sourced from the updated global policy and generated MCP entries remain enabled for generic, Codex, and Gemini profiles. Do not add direct Serena/CodeGraph MCP servers by default.

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run: `python -m pytest tests/test_v1_5_reliability.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `test: cover agent config installation contract`

### Task 4: Install current global Codex and Gemini configuration

**Files:**
- Modify: Codex global `AGENTS.md`, `instructions.md`, `config.toml` and `local-ai-orchestrator` skill locations
- Modify: Gemini global `GEMINI.md`, `settings.json` and `local-ai-orchestrator` skill locations

- [ ] **Step 1: Apply only managed policy/MCP/skill updates**

Merge the updated policy into Codex `AGENTS.md` and Gemini `GEMINI.md`, preserve unrelated text, update global orchestration instructions, copy the repository skill to all existing Codex/Gemini skill locations, and ensure both MCP configs point to the package-native server with `LOCAL_AI_AGENT=codex` or `gemini`.

- [ ] **Step 2: Verify config shape**

Parse Codex TOML and Gemini JSON; assert `local-ai` and the configured direct AGY server remain enabled where already configured, with no unrelated top-level settings removed.

### Task 5: Verify, review, and release

**Files:**
- Modify: `docs/superpowers/specs/2026-09-02-agent-routing-design.md`
- Modify: `docs/MCP_AND_AGENTS.md`
- Modify: `README.md`

- [ ] **Step 1: Run targeted tests through `local_ai_command`**

Run: `python -m pytest tests/test_mcp_agent_routing.py tests/test_v1_5_reliability.py -q`

- [ ] **Step 2: Run repository validation through `local_ai_command`**

Run: `python -m compileall -q src mcp tools tests`

Run: `python -m pytest -q`

Run: `python tools/selftest.py`

- [ ] **Step 3: Review diff and installed configuration**

Inspect `git diff`, verify only intended repository files changed, and compare Codex/Gemini managed blocks plus skill copies against the source policy.

- [ ] **Step 4: Run security-focused review**

Review for accidental secret/config loss, unsafe MCP command changes, prompt/source telemetry leakage, and unintended AGY/Hub authority inversion.

- [ ] **Step 5: Commit final repository changes**

Commit message: `feat: route bounded work through local ai hub`
