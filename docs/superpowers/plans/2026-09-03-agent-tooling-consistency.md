# Agent Tooling Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align installed agent instructions and local-model skills with the live AGY and Local AI Hub MCP surfaces.

**Architecture:** AGY remains a Codex-owned peer-agent route. Local AI Hub remains the seven-tool, cache-first surface; Serena and CodeGraphContext remain Hub-managed by default. Portable manifests stay Hub-only unless a host explicitly configures extra direct servers.

**Tech Stack:** Markdown skills/policies, Codex TOML/JSON MCP configuration, Python repository tooling.

**Spec:** Existing audit findings from 2026-09-03; live MCP tool list and `local_ai_status`/`agy_doctor` checks.

## Global Constraints

- Preserve direct AGY ownership outside Local AI Hub.
- Use `local_ai_task` for bounded Ollama work; use `qwen2.5-coder:7b` by default and `heavy_code` only for complex/high-risk work.
- Keep Serena/CodeGraphContext behind the compact Hub surface by default.
- Do not add provider API keys, blanket permission bypasses, or unbounded retries.

---

### Task 1: Align AGY instructions

**Files:**
- Modify: user Codex `AGENTS.md`
- Modify: user Codex `skills/subagent-orchestrator/SKILL.md`
- Modify: repository `skills/local-ai-orchestrator/SKILL.md`
- Modify: installed copies of `local-ai-orchestrator` in Codex and agent skill roots

- [x] Replace unavailable legacy AGY helper references with direct `mcp__agy__agy*` routes and explicit modes.
- [x] Replace the ambiguous `antigravity-subagents` route wording with the installed `agy` MCP server/tool names.
- [x] Preserve workspace validation, sandbox, `allow_write`, timeout and integration ownership rules.

### Task 2: Align Ollama skills

**Files:**
- Modify: installed Codex `skills/ollama-local-models/SKILL.md`
- Modify: installed agent `skills/ollama-quality-routing/SKILL.md`

- [x] Route status through `local_ai_status` and bounded work through `local_ai_task`.
- [x] Document current fast/smart model roles and named advisory profiles.
- [x] Remove references to unavailable `ollama_*` MCP tools and stale 14B/deepseek defaults.

### Task 3: Clarify generated manifest boundary and verify

**Files:**
- Modify: repository `docs/MCP_AND_AGENTS.md`
- Modify: repository `README.md`
- Modify: repository `generated/agent-policy.md`

- [x] State that portable generated manifests intentionally contain `local-ai`; AGY is host-managed and direct Serena/CodeGraph are opt-in.
- [x] Check all edited policy/skill copies for stale tool names.
- [x] Validate JSON/TOML/Markdown consistency and run targeted repository checks.
