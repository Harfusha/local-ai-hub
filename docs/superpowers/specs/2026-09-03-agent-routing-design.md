# AGY-first delegation routing design

## Goal

Make AGY the default peer agent for delegated work across every instruction surface in this installation. Keep the main Codex agent as orchestrator, integrator, and final owner.

## Routing policy

For every task with useful bounded independent work, delegate to AGY first after the required local indexed evidence step. Prefer AGY for research, planning, implementation, review, testing support, and other bounded sidecar work. Use the direct AGY MCP bridge with explicit scope, workspace, sandbox, timeout, and write permission.

Do not use the native Codex `multi_agent_v1__spawn_agent` path unless at least one condition holds:

1. The user explicitly requests a Codex subagent.
2. The task requires a Codex-only capability or native Codex context/tool lifecycle.
3. AGY is unavailable after one bounded attempt.

Skip delegation for trivial answers, pure evidence lookups, security/privacy-restricted work, or tasks with no useful independent scope. Never duplicate scopes. Codex retains final decisions, edits, integration, and verification ownership.

## Scope

Synchronize the policy in:

- `AGENTS.md`
- `README.md`
- `docs/MCP_AND_AGENTS.md`
- `skills/local-ai-orchestrator/SKILL.md`
- generated policy/setup text identified by repository search
- installed copies at `~/.agents/skills/local-ai-orchestrator/SKILL.md` and `~/.codex/skills/local-ai-orchestrator/SKILL.md`

Wording must explicitly name AGY as first choice and native `spawn_agent` as exception-only. Preserve the Local AI Hub evidence and command-validation gates.

## Verification

Search all tracked and generated instruction text for contradictory routing language. Confirm every remaining native-subagent mention is either an exception or a tool/interface description. Run the repository's bounded documentation/policy checks if available; otherwise perform a syntax/content consistency check.
