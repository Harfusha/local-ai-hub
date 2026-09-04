# Ollama Advisory Subagents Design

**Date:** 2026-09-03  
**Status:** Awaiting user review

## Goal

Add named Ollama subagent profiles to Local AI Hub, inspired by the external Codex/Ollama subagent pattern, while keeping every local model advisory-only. The profiles must use Local AI Hub tooling directly for repository evidence and must never edit files, execute commands, or bypass Hub policy.

## Constraints

- Keep the compact seven-tool MCP surface; extend existing `local_ai_task` and `local_ai_repo` contracts instead of adding a second MCP server.
- Reuse `ToolAwareLocalAgent`, `LocalAgentPipeline`, existing cache, async jobs, scheduler, telemetry, evidence store, and model policy.
- Expose only read-only Hub tools to subagents: preprocessing context, deterministic facts, code index, semantic symbols, code graph, repository search, RAG search, evidence lookup, and bounded file slices.
- Do not expose command execution, write APIs, worktrees, or direct filesystem mutation.
- Match output language to the task language; preserve identifiers, paths, line numbers, code, errors, and uncertainty verbatim.
- Use installed `qwen2.5-coder:7b` as the default model. Resolve configured model aliases only when the selected model is available; otherwise return a bounded fallback/error without silently selecting an unrelated provider.
- Preserve cache keys, tenant isolation, evidence freshness, async delivery, and metadata-only telemetry.

## Profiles

### `qwen-explorer`

Read-only repository reconnaissance. Starts with preprocessed and deterministic evidence, then requests the smallest required indexed or exact evidence slice. Returns candidate files/symbols, evidence IDs, confidence, missing evidence, and risks.

### `qwen-drafter`

Read-only solution drafting for bounded microtasks. Consumes explorer evidence or Hub context, proposes implementation steps, pseudocode, patch guidance, edge cases, and validation commands. It never applies the proposal.

### `qwen-critic`

Independent read-only review. Checks supplied candidate output against Hub evidence, impact data, and security/review signals. Returns concrete correctness gaps, unsafe assumptions, missing tests, and unresolved uncertainty. It must not praise, rewrite files, or claim validation it did not run.

All profiles use a shared language-aware system contract and explicit `ADVISORY_ONLY` output metadata.

## API and routing

Extend `local_ai_task` with optional `profile`, `root`, and `workspace` fields. Existing calls without `profile` retain current behavior. A named profile routes through `ToolAwareLocalAgent` when a repository root is supplied; non-repository calls use the existing bounded generation path with the profile system prompt.

Extend `local_ai_repo` delegation with the same optional profile field. This gives repository-aware subagents one canonical entry point while keeping the MCP tool count unchanged.

Profile resolution is deterministic:

1. Validate profile name and normalize aliases.
2. Load profile defaults from configuration.
3. Select the configured model only if it is present in the bounded model inventory.
4. Apply role-specific tool allowlists, context/token limits, temperature, and max steps/calls.
5. Run deterministic/preprocessed bootstrap before local model inference.
6. Run the read-only tool loop only when bootstrap evidence is insufficient.
7. Return compact result plus profile, model, tools used, cache state, language, and advisory-only metadata.

## Configuration

Add an opt-in profile section to defaults and user configuration. Defaults use the installed fast model and conservative limits. Profile configuration may change model names and budgets, but cannot add write or command capabilities.

Example shape:

```toml
[ollama_subagents]
enabled = true
default_profile = "qwen-explorer"
language = "match_input"

[ollama_subagents.profiles.qwen-explorer]
model = "qwen2.5-coder:7b"
role = "explorer"
max_steps = 3
max_tool_calls = 6
max_tokens = 700

[ollama_subagents.profiles.qwen-drafter]
model = "qwen2.5-coder:7b"
role = "drafter"
max_steps = 3
max_tool_calls = 6
max_tokens = 1100

[ollama_subagents.profiles.qwen-critic]
model = "qwen2.5-coder:7b"
role = "critic"
max_steps = 3
max_tool_calls = 6
max_tokens = 800
```

## Error handling

- Unknown profile: structured non-retryable error listing valid profiles.
- Disabled profiles: structured unsupported response; existing task actions remain usable.
- Missing model: one bounded model inventory check, then deterministic/indexed fallback where sufficient; no provider substitution.
- Ollama/tool-call incompatibility: return advisory result with `degraded=true` and available Hub evidence, never retry in a loop.
- Stale evidence: expose freshness failure and request a new bounded Hub slice; never present stale coordinates as current.
- Timeout/cancellation: use existing async job and scheduler boundaries; preserve terminal state and do not leak subprocesses.

## Testing

Add focused tests before implementation for:

- profile catalog, aliases, defaults, and invalid profile handling;
- model selection against installed/configured inventory;
- language-match prompt contract and identifier preservation;
- per-profile read-only tool allowlists, proving command/write tools are absent;
- Hub bootstrap ordering before model inference;
- tool-loop limits, timeout, cancellation, and degraded fallback;
- cache key isolation by profile/model/root/context revision;
- sync and async MCP responses preserving existing contracts;
- telemetry containing profile/model/tool-count metadata only, never prompts or source text;
- backward compatibility for existing `local_ai_task` and `local_ai_repo` calls.

## Acceptance criteria

1. Three named profiles are discoverable through existing Hub tools.
2. Every profile uses Hub tooling for repository context before inference.
3. No profile can write files, execute commands, create worktrees, or call an external provider directly.
4. Default model is `qwen2.5-coder:7b`; unavailable models fail or fall back through bounded Hub logic.
5. Output follows input language while preserving technical tokens.
6. Existing seven-tool MCP surface, cache, async delivery, telemetry, and legacy calls remain compatible.
7. Focused tests pass, then the full validation suite passes.
