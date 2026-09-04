# AGY-first Delegation Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AGY the default delegated peer across all active Local AI Hub routing instructions, with native Codex subagents limited to explicit or technically necessary exceptions.

**Architecture:** Keep Codex as orchestrator, final editor, integrator, and verifier. Align the active policy (`AGENTS.md`), user-facing docs, skill text, generated policy, and setup template around one AGY-first decision rule. Historical plans/changelogs remain unchanged.

**Tech Stack:** Markdown policy files, Python setup template, repository search and targeted documentation checks.

---

### Task 1: Synchronize active routing policy

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/MCP_AND_AGENTS.md`
- Modify: `skills/local-ai-orchestrator/SKILL.md`
- Modify: `tools/setup.py`
- Modify: `generated/agent-policy.md`
- Modify: `~/.agents/skills/local-ai-orchestrator/SKILL.md`
- Modify: `~/.codex/skills/local-ai-orchestrator/SKILL.md`

- [ ] Replace discretionary wording with: delegate every useful bounded independent task to AGY first after required indexed evidence; use native `multi_agent_v1__spawn_agent` only for explicit Codex-subagent requests, Codex-only capability/context, or one bounded AGY-unavailable fallback.
- [ ] Preserve skips for trivial answers, pure evidence lookups, security/privacy restrictions, and tasks without useful independent scope.
- [ ] Preserve AGY direct invocation, explicit scope/workspace/sandbox/timeout/write controls, no duplicate scopes, and Codex ownership of final integration.
- [ ] Keep historical `docs/superpowers/plans/*` and `CHANGELOG.md` entries unchanged.

### Task 2: Verify policy consistency

**Files:**
- Verify: all files named in Task 1

- [ ] Search active instruction text for old discretionary phrases such as `Codex decides whether to use`, `AGY is preferred`, and `native Codex subagents and AGY are peer agents`.
- [ ] Confirm remaining native-subagent mentions describe only the exception rule or tool/interface behavior.
- [ ] Run the repository's available bounded policy/documentation checks; if none exist, perform a targeted content and Markdown consistency check.
- [ ] Report exact files changed and verification results. No Git commit is possible because this installation directory is not a Git worktree.
