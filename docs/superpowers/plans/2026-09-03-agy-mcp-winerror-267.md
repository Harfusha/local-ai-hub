# AGY MCP WinError 267 Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AGY MCP delegation reliable on Windows and document the required workspace, `--add-dir`, sandbox, and Local AI Hub routing contract globally.

**Architecture:** The bridge resolves an existing workspace before any subprocess call. It uses that directory as `cwd` and passes the same absolute path to AGY through `--add-dir`; invalid workspaces return a structured diagnostic instead of `WinError 267`. Global MCP configs and agent instructions share one explicit contract.

**Tech Stack:** Python 3.11+, MCP JSON-RPC, AGY CLI, Codex TOML, Gemini JSON/Markdown.

---

### Task 1: Harden AGY workspace transport

**Files:**
- Modify: `<USER_HOME>/.gemini/antigravity/scratch/codex-subagent-bridge/bridge_core.py`
- Test: `<USER_HOME>/.gemini/antigravity/scratch/codex-subagent-bridge/test_bridge.py`

- [x] Add a regression test requiring `--add-dir` for an existing workspace.
- [x] Add a regression test proving invalid workspaces never reach subprocess creation and never expose `WinError 267`.
- [x] Resolve and validate workspace paths before Local AI Hub or AGY calls.
- [x] Pass validated absolute workspace to both `cwd` and `--add-dir`.
- [x] Run `python -B test_bridge.py`; expected: 7 tests pass.

### Task 2: Synchronize global MCP and agent contract

**Files:**
- Modify: `<CODEX_HOME>/config.toml`
- Modify: `<CODEX_HOME>/AGENTS.md`
- Modify: `<GEMINI_HOME>/settings.json`
- Modify: `<GEMINI_HOME>/GEMINI.md`
- Modify: `<GEMINI_HOME>/antigravity-cli/mcp_config.json`
- Modify: `<GEMINI_HOME>/antigravity-cli/settings.json`
- Modify: `<GEMINI_HOME>/antigravity/scratch/codex-subagent-bridge/mcp_config.json`

- [x] Keep Local AI Hub MCP package-native and add the AGY bridge MCP entry wherever the host loads global MCP servers.
- [x] Set absolute AGY executable path in bridge environment; preserve sandbox and permission prompts.
- [x] Document: use absolute existing workspace, pass `--add-dir`, never use `--dangerously-skip-permissions`, route bounded work through Local AI Hub first.

### Task 3: Synchronize reusable skills

**Files:**
- Modify: `skills/local-ai-orchestrator/SKILL.md`
- Modify: `<USER_HOME>/.agents/skills/local-ai-orchestrator/SKILL.md`
- Modify: `<CODEX_HOME>/skills/local-ai-orchestrator/SKILL.md`
- Modify: `<GEMINI_HOME>/skills/local-ai-orchestrator/SKILL.md`
- Modify: `<GEMINI_HOME>/config/skills/local-ai-orchestrator/SKILL.md`
- Create: `<GEMINI_HOME>/antigravity-cli/skills/local-ai-hub.md`

- [x] Add AGY bridge usage and Windows workspace rules to canonical and installed skills.
- [x] Keep all copies content-equivalent for routing, `WinError 267`, `--add-dir`, sandbox, and fallback behavior.

### Task 4: Verify

- [x] Validate JSON/TOML and all skill/instruction markers.
- [x] Run bridge tests, Python compileall, project pytest, and selftest through the approved command path.
- [x] Perform one non-mutating AGY help check and inspect final diffs.
