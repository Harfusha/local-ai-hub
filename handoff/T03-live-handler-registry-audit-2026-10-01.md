# T03 live handler / registry coverage audit

Date: 2026-10-01
Root: `C:\Users\Adam\.local-ai-hub`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Worktree: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`

## Scope and method

Read-only static comparison of the eight registered `local_ai_*` function signatures in `src/local_ai_hub/mcp_server.py` against each registry contract's authored properties, conditional properties, selector field, and shared response-budget fields in `src/local_ai_hub/operation_contracts.py`. Used Python AST parsing; no module imports, builds, or tests. Root source remained unmodified. No `http_server.py` or `client.py` changes.

## Complete signature/property difference

Counts include selector and common response-budget properties. “Missing” means handler has named input but registry schema does not expose it.

| Tool | Handler / registry fields | Missing handler inputs | Source-backed use |
|---|---:|---|---|
| `local_ai_status` | 10 / 7 | `adoption_signal: Literal["", "bypassed"]`; `target_tool: str`; `target_action: str` | Validates explicit adoption-bypass telemetry before status projection (`mcp_server.py:1259-1273`). |
| `local_ai_repo` | 45 / 35 | `include_diagnostics: bool`; `clone_id`, `worktree_id`, `branch`, `repository_id`, `session_id`, `repository_revision: str`; `is_worktree: bool`; `parent_root: str`; `steps: list[dict[str, Any]] \| None` | Context metadata enters `context_compile` (`mcp_server.py:2190-2202`); `steps` drives `pipeline` (`2116+`); worktree flags enter `preprocess` (`2175-2176`). |
| `local_ai_task` | 62 / 57 | `phase`, `preload_profile`, `repository_revision: str`; `focus`, `changed_paths: list[str] \| None` | Passed to `_load_task_context` before semantic execution (`mcp_server.py:1445-1460`). |
| `local_ai_rag` | 14 / 14 | — | Complete after T03 RAG fields. |
| `local_ai_command` | 23 / 23 | — | Complete after T03 command fields. |
| `local_ai_coord` | 44 / 44 | — | Complete after T03 coord fields. |
| `local_ai_work` | 18 / 17 | `extra_fields: list[str] \| None` | Accepted by signature, but never read in handler body (`mcp_server.py:2863-2887`); decide whether to remove or wire to projection. |
| `local_ai_artifact` | 10 / 10 | — | Complete. |

## Action-specific regression proposal

Run through registered MCP dispatch with a fresh registration or stubbed handler, no handler body/network effects. Add positive and negative pairs:

1. **Status adoption fields:** `detail="brief"`, `adoption_signal="bypassed"`, supported `target_tool`/`target_action` reaches handler; missing target or stray target without signal rejects before dispatch.
2. **Repo context metadata:** `context_compile` accepts `include_diagnostics`, clone/worktree IDs, branch, repository/session IDs, revision, and existing `changed_paths`; `search` rejects these once fields are action-scoped.
3. **Repo pipeline:** `pipeline` accepts a non-empty `steps` array; `search` rejects `steps`.
4. **Repo preprocess:** `preprocess` accepts `is_worktree`/`parent_root`; `preprocess_status` rejects them.
5. **Task context:** a semantic action such as `reason` accepts phase/focus/preload/changed-path/revision inputs; `cancel` rejects those fields after action scoping.
6. **Work projection:** cover `extra_fields` only after deciding semantics: either remove unused argument, or pass it into `_compact` and verify selected response fields survive.

Keep existing C1-C3 receipts: eight prior dispatch cases and corrected feature-enabled `batch_replace` selector **1/1 passed**. Do not rerun the green selector without a relevant change. Root integration/validation remains under T20 slot control.
