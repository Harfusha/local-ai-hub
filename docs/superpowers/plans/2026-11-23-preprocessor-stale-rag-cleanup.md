# Implementation plan: stale RAG cleanup

- Hub plan: `plan_hub_mcp_responsiveness`
- Hub task: `task_repair_stale_rag_cleanup`
- Specification: [bounded stale RAG reference cleanup](../specs/2026-11-23-preprocessor-stale-rag-cleanup.md)

## Goal

Prevent stale-reference cleanup from holding one long SQLite write transaction
that stalls Hub preprocessing and repository operations.

## Steps

1. Update `src/local_ai_hub/preprocess_rag.py` to apply stale-path metadata and
   FTS cleanup in eight-path transactions. Preserve the existing hash and
   generation checks.
2. Add a focused regression case to
   `tests/unit/test_preprocess_rag_pending.py` with seventeen stale paths and
   assert the cleanup batches are `8`, `8`, and `1`.
3. Run the focused preprocessing test module and inspect the diff.
4. Restart the installed Hub after validation. Check Hub status and one
   repository MCP action; investigate the status HTTP 500 separately if it
   remains.
