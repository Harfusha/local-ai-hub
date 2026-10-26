---
name: tool-orchestration
description: >-
  Use for any multi-tool or multi-step engineering task across any project.
  Guides phased execution: Discover -> Inspect -> Reason -> Act -> Verify -> Review,
  orchestrating Serena code intelligence, Local AI Hub, Context7 documentation, and project test runners.
---

# Global Tool Orchestration

Coordinate available tools and capabilities systematically across six distinct execution phases.

## 6-Phase Execution Lifecycle

```
[1. Discover] --> [2. Inspect] --> [3. Reason] --> [4. Act] --> [5. Verify] --> [6. Final Review]
```

### 1. Discover
- Clarify domain, objective, and requirements.
- Identify project boundaries, configuration, and technology stack.
- **Session Briefing & Coordination**: Call `local_ai_coord(action="session_briefing")` or query `local_ai_coord(action="board_summary")` to inspect active multi-agent work, board deliverables, and blockers before starting.
- **Local AI Hub Adaptive Retrieval**: reuse fresh sufficient repository evidence. For exact file or symbol lookups, use bounded indexed/source lookup directly. For non-trivial work without sufficient fresh evidence, call `local_ai_repo(action="context", mode="adaptive")` once with the task/context before broad native discovery. The orchestrator fuses deterministic/indexed evidence, CodeIndex, Serena, bounded lexical search and RAG; it ranks agreement, deduplicates and preserves path diversity. Send the task/context directly; do not manufacture a long grep-term list. Preprocess only when the root is unindexed or its evidence is stale; never wait, poll or force-refresh it. Bounded native reads of a known path and slice remain permitted when needed.
- Use `local_ai_repo(action="solve")` only after the grounded context pack when bounded implementation reasoning is needed.
- For external library questions: query **Context7** (`resolve-library-id`, `query-docs`).
- For codebase overview: list project structure, active Git branch (`local_ai_repo(action="git_status")`), and recent changes.

### 2. Inspect
- Inspect definitions, symbols, and diagnostics before editing.
- Reuse the adaptive context pack and its evidence IDs first; fetch only missing exact slices.
- Use **Serena MCP** or **Local AI Code Index**:
  - `local_ai_repo(action="code_index")`: locate symbol definitions and code snippets.
  - `local_ai_repo(action="impact")`: calculate callers and blast radius before modifying symbols.
  - `local_ai_artifact(action="slice")`: inspect exact line ranges without reading whole files.
  - `local_ai_repo(action="package_audit")`: check package security advisories and dependencies.

### 3. Reason
- Formulate an explicit plan or mental model before making mutations.
- Assess risk, side-effects, and backward compatibility using `local_ai_repo(action="refactor_impact")`.
- **Local AI Hub Delegation**:
  - For the hardest reasoning: use the 7B tier via `local_ai_task`.
  - For routine code synthesis or second opinions: use the 1.5B tier; use 3B for complex logic and difficult debugging.
- **Fallback Rule**: If Local AI Hub is unreachable, fall back immediately to internal reasoning without blocking.

### 4. Act
- Apply precise, localized code edits.
- **Resource Semaphores & Signal Sync**: When accessing exclusive tools or single-instance processes (e.g. Unity Editor, specialized hardware, single-writer state), acquire lock via `local_ai_coord(action="semaphore_acquire", name="...", owner=..., capacity=1, timeout=30)` and release promptly via `semaphore_release`. Never busy-poll; use `local_ai_coord(action="wait_for_event")` to await signals.
- **Project Board Tracking**: Keep work visible across sessions and agents by creating or updating Kanban deliverables via `local_ai_coord(action="board_item_create"|"board_item_update")`.
- Use targeted file edits (`replace_file_content` or surgical patches).
- **Auto-Resolve Imports**: Use `local_ai_repo(action="resolve_imports")` to automatically fill missing namespaces/imports.
- **Diff Validation**: Use `local_ai_repo(action="validate_patch")` before committing structural edits.
- Avoid unnecessary mass rewrites; preserve existing comments, formatting, and conventions.

### 5. Verify
- Run actual project test suites via the agent host's native command tool (e.g. `run_command`):
  - Python: `pytest` / `python -m unittest`
  - .NET / C#: `dotnet test`
  - JavaScript / TypeScript: `npm test` / `pnpm test` / `vitest` / `jest`
  - Rust: `cargo test`
  - Go: `go test ./...`
- **Rule of Authenticity**: Never fabricate test output. Confirm actual execution and zero failures.

### 6. Final Review
- Review unified diff of changed files (`local_ai_repo(action="review_diff")` or `git diff`).
- Run `local_ai_repo(action="security_audit")` for secrets or injection risks.
- Clean and commit changes with a concise, descriptive commit message.

### MCP Response Economy
- `response_budget.returned_tokens` measures the final serialized response envelope in `estimated_tokens` and stays at or below the requested budget.
- Preserve protected status, error, evidence, and context-identity fields; keep exact detail artifact-backed.
- Claim savings only with a current `baseline_evidence_id`; report signed `token_savings_delta_est`, including negative values; keep `protocol_tokens_est`, `schema_tokens_est`, and `local_compute_reused_tokens_est` separate.
- Reject `max_response_tokens` below 128; never raise the request silently.
- For Hub outages, native fallback requires explicit `terminal=true` and `retryable=false`; for Hub-unknown commands, require `native_fallback_allowed=true` plus native-tool authorization.
- On `outcome_unknown` or `in_progress`, do independent work; never poll or repeat the identical operation.
