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
- **Local AI Hub Adaptive Search**: Query `local_ai_repo(action="solve")` for hybrid AST + semantic code discovery.
- For external library questions: query **Context7** (`resolve-library-id`, `query-docs`).
- For codebase overview: list project structure, active Git branch (`local_ai_repo(action="git_status")`), and recent changes.

### 2. Inspect
- Inspect definitions, symbols, and diagnostics before editing.
- Use **Serena MCP** or **Local AI Code Index**:
  - `local_ai_repo(action="code_index")`: locate symbol definitions and code snippets.
  - `local_ai_repo(action="impact")`: calculate callers and blast radius before modifying symbols.
  - `local_ai_artifact(action="slice")`: inspect exact line ranges without reading whole files.
  - `local_ai_repo(action="package_audit")`: check package security advisories and dependencies.

### 3. Reason
- Formulate an explicit plan or mental model before making mutations.
- Assess risk, side-effects, and backward compatibility using `local_ai_repo(action="refactor_impact")`.
- **Local AI Hub Delegation**:
  - For complex logic, architectural choices, or difficult debugging: delegate to **Qwen3.5-9B** smart tier via `local_ai_task`.
  - For fast routine code synthesis or second opinion: delegate to **Qwen2.5-Coder-7B** fast tier via `local_ai_task`.
- **Fallback Rule**: If Local AI Hub is unreachable, fall back immediately to internal reasoning without blocking.

### 4. Act
- Apply precise, localized code edits.
- Use targeted file edits (`replace_file_content` or surgical patches).
- **Auto-Resolve Imports**: Use `local_ai_repo(action="resolve_imports")` to automatically fill missing namespaces/imports.
- **Diff Validation**: Use `local_ai_repo(action="validate_patch")` before committing structural edits.
- Avoid unnecessary mass rewrites; preserve existing comments, formatting, and conventions.

### 5. Verify
- Run actual project test suites via `local_ai_command`:
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
