---
name: tool-orchestration
description: Use for multi-step engineering work across repositories.
---

# Tool Orchestration

Use this sequence for engineering tasks: discover, inspect, reason, act, verify, review.

## Discover and inspect

On first work in each stable repository root, resolve the absolute Git root and inspect `.local-ai.toml` plus any applicable `.local-ai.worktree.toml`. If settings are missing or incomplete, add only evidence-backed exclusions, uncommon text/binary extensions, pinned docs, and entry points; preserve existing values and use Hub defaults when sufficient. Then call `local_ai_repo(action="preprocess", root=ABS_ROOT)` once for idempotent registration. Do not force-refresh or poll asynchronous preprocessing.

Reuse fresh repository evidence before adaptive retrieval or native broad discovery.

- Start with `local_ai_repo` for bounded repository evidence. Supported actions: `search`, `code_index`, `context`, `solve`, `review_diff`, `callers`, `dead_code`, and `preprocess` for registration.
- Use exact artifact slices for source details. Use adaptive context only when indexed evidence is insufficient.
- Check the active MCP schema before relying on any tool or action.

## Reason and act

- Define scope and acceptance criteria. For substantial work, create a task contract and query relevant memory with supported `local_ai_coord` actions.
- Make localized edits and preserve unrelated user changes.
- Use `local_ai_task` for bounded semantic reasoning, review or second opinion when an approved backend is available. Deterministic/indexed evidence remains authoritative for exact facts and diffs.

## Verify and review

- Run bounded project checks with the host-native command tool; the Hub has no command-runner tool.
- Use `local_ai_repo(action="review_diff")` when relevant, then inspect the diff and validation output.
- Do not claim completion without evidence. Do not commit, push or publish unless the user explicitly asks.
