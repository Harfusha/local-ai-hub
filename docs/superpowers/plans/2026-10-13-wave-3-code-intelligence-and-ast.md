# Wave 3 Implementation Plan: Code Intelligence & AST

> **Governing workflow:** Follow [Simplified Worktree and Integration Process](../specs/2026-10-07-simplified-worktree-integration.md). The primary agent implements, reviews, and integrates on current `master`. Subagents and isolated worktrees are optional for independent implementation with disjoint scope; audits and routine work remain with the primary agent. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide deep, accurate code understanding across all major languages (Python, TypeScript, C#, Go, Rust) with full symbol graphs, AST-level refactoring, and line-level context deduplication.

**Architecture:** Modifies `code_index.py`, `deterministic.py`, `rag.py`, `treesitter_parser.py`, `mcp_server.py`, and `agent_memory.py`. Adds MCP actions for `callees`, `implementations`, and `declaration`. Implements regex block-level chunking when tree-sitter is disabled on Windows. Merges overlapping line windows in context pack outputs.

**Tech Stack:** Python 3.11+, SQLite 3 (Recursive CTEs), Tree-sitter, Regex AST parsers, Pytest.

---

### Task 38: Expose `callees`, `implementations`, and `declaration` in MCP (#82, #83)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:2840-2880, 3200-3215`
- Modify: `mcp/local-ai/local_ai_repo.json`
- Test: `tests/unit/test_mcp_symbol_graph_actions.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_mcp_symbol_graph_actions.py
def test_mcp_callees_action_dispatches_correctly(monkeypatch):
    captured = {}
    class DummyClient:
        def post(self, url, payload, **kwargs):
            captured.update({"url": url, "payload": payload})
            return {"success": True, "callees": [{"symbol": "bar", "path": "test.py"}]}
    monkeypatch.setattr("local_ai_hub.mcp_server.CLIENT", DummyClient())
    from local_ai_hub.mcp_server import local_ai_repo
    res = local_ai_repo(action="callees", root=".", query="foo")
    assert captured["url"] == "/api/code/callees"
    assert captured["payload"]["symbol"] == "foo"
```

- [ ] **Step 2: Implement fix in `mcp_server.py` and schema**
1. Add `callees`, `implementations`, `declaration` to `RepoAction` enum in `mcp_server.py` and `local_ai_repo.json`.
2. Map them to `/api/code/callees`, `/api/code/implementations`, and `/api/code/declaration` endpoints.
3. In `http_server.py`, wire these endpoints to `APP.code_index.find_callees`, `find_implementations`, and `find_declaration`.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(code_index): expose callees, implementations, and declaration in MCP local_ai_repo"`

---

### Task 39: AST-Aware Regex Chunker for Non-Python Languages (#63)

**Files:**
- Modify: `src/local_ai_hub/rag.py:510-560`
- Modify: `src/local_ai_hub/treesitter_parser.py:40-70`
- Test: `tests/unit/test_regex_ast_chunker.py`

- [ ] **Step 1: Write failing test with TypeScript and C# source files**
Verify that chunking a TypeScript file (`.ts`) or C# file (`.cs`) does not split in the middle of a function body when tree-sitter is unavailable.

- [ ] **Step 2: Implement fix in `rag.py`**
Implement `_regex_ast_chunks(text: str, language: str) -> list[str]` with regexes matching function/class block declarations (`export class ... {`, `public async Task ... {`, `func ... {`). Split code cleanly at outermost closing braces (`}`) rather than arbitrary character/line counts.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(rag): add AST-aware regex chunker for TS, CS, Go, Rust when tree-sitter is disabled"`

---

### Task 40: Context Line Overlap Deduplication & Merge (#65)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:2800-2850`
- Modify: `src/local_ai_hub/services.py:5120-5160`
- Test: `tests/unit/test_context_overlap_dedup.py`

- [ ] **Step 1: Write test verifying overlapping line slices merge into a single slice**

```python
# tests/unit/test_context_overlap_dedup.py
from local_ai_hub.deterministic import DeterministicEngine

def test_merge_overlapping_slices():
    slices = [
        {"path": "foo.py", "start_line": 10, "end_line": 25, "text": "line10\nline25"},
        {"path": "foo.py", "start_line": 20, "end_line": 35, "text": "line20\nline35"},
    ]
    merged = DeterministicEngine.merge_overlapping_slices(slices)
    assert len(merged) == 1
    assert merged[0]["start_line"] == 10
    assert merged[0]["end_line"] == 35
```

- [ ] **Step 2: Implement `merge_overlapping_slices`**
Sort slices by `(path, start_line)`. If `current.start_line <= previous.end_line + 2`, merge the ranges into `[previous.start_line, max(previous.end_line, current.end_line)]` and re-read the unified slice from source.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(context): merge overlapping code slices to save 15-30% token budget"`

---

### Task 41: Function Signatures & Type Annotations in FQN Symbols (#64)

**Files:**
- Modify: `src/local_ai_hub/code_index.py:850-900`
- Test: `tests/unit/test_symbol_signatures.py`

- [ ] **Step 1: Write test verifying `find_symbol` includes `signature` for TypeScript and Python methods**
- [ ] **Step 2: Implement fix**
When indexing symbols in `code_index.py`, extract the full method signature (parameter names, types, return type) using regex or AST, and populate the `signature` column in table `symbols`.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(code_index): extract and store method signatures and return types in symbol index"`

---

### Task 42: Recursive CTE for `traverse_graph` in Agent Memory (#96)

**Files:**
- Modify: `src/local_ai_hub/agent_memory.py:450-490`
- Test: `tests/unit/test_memory_graph_cte.py`

- [ ] **Step 1: Write test verifying `traverse_graph` executes single SQL query**
- [ ] **Step 2: Implement fix**
Replace Python BFS while-loop with SQLite recursive CTE:
```sql
WITH RECURSIVE graph_cte(entity, depth) AS (
    SELECT ? AS entity, 0 AS depth
    UNION
    SELECT CASE WHEN r.source_entity = g.entity THEN r.target_entity ELSE r.source_entity END,
           g.depth + 1
    FROM graph_cte g
    JOIN agent_relations r ON (r.source_entity = g.entity OR r.target_entity = g.entity)
    WHERE g.depth < ?
)
SELECT DISTINCT * FROM graph_cte LIMIT ?;
```
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(memory): use recursive CTE in SQLite for single-query graph traversal"`

---

### Task 43: Tree-sitter Parser in Isolated Subprocess Worker (#19)

**Files:**
- Modify: `src/local_ai_hub/treesitter_parser.py:30-80`
- Test: `tests/unit/test_treesitter_isolated_worker.py`

- [ ] **Step 1: Write test verifying tree-sitter runs in worker process without crashing main process on access violation**
- [ ] **Step 2: Implement fix**
On Windows Python 3.13, run tree-sitter parsing in a separate pool worker subprocess via IPC. If the worker crashes with an OS access violation, return graceful fallback and keep the main process alive.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(treesitter): isolate tree-sitter parsing in worker process to protect Hub on Windows"`

---

### Task 44: SQLite Parameter Overflow Guard (#99)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:1200-1240`
- Modify: `src/local_ai_hub/code_index.py:2700-2730`
- Test: `tests/unit/test_sqlite_parameter_overflow.py`

- [ ] **Step 1: Write test passing 2,000 items into `batch_replace` and `files_needing_reindex`**
- [ ] **Step 2: Implement fix**
Wrap all `WHERE column IN (...)` dynamic query generators with a chunker:
```python
def chunked_in_query(items: list[Any], chunk_size: int = 250):
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]
```
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(sqlite): guard against SQL variable limit overflow by chunking IN queries to 250 items"`

---

### Task 45: Symbol-Aware Context Packs with Complete Function Bodies (#11)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:2780-2820`
- Test: `tests/unit/test_symbol_context_pack_boundaries.py`

- [ ] **Step 1: Write test verifying `context` returns complete function or class definition, not just enum header**
- [ ] **Step 2: Implement fix**
Use AST node start and end line bounds from the symbol index instead of fixed +/- 4 line context windows.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(context): expand code context pack slices to full symbol boundaries"`

---

### Task 46: Honest Result Freshness via Mtime Verification (#16)

**Files:**
- Modify: `src/local_ai_hub/code_index.py:1180-1220`
- Test: `tests/unit/test_code_index_freshness_check.py`

- [ ] **Step 1: Write test verifying index returns `stale=True` if file on disk has newer mtime than index**
- [ ] **Step 2: Implement fix**
Before returning `confidence: 0.925`, inspect file `mtime`. If changed, mark result as `stale: True` and trigger background reindex.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(code_index): check file mtime before returning high-confidence search results"`

---

### Task 47: AST Skeletonize Directly from Code Index (#34)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:7320-7360`
- Test: `tests/unit/test_skeletonize_from_index.py`

- [ ] **Step 1: Write test skeletonizing a large source file without sending file content**
- [ ] **Step 2: Implement fix**
In `skeletonize_code`, if `path` is registered, construct the skeleton directly from table `symbols` (classes, functions, signatures) without reading and parsing the file.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(ast): construct file skeleton directly from indexed symbols"`

---

### Task 48: Static Export Validation in `resolve_imports` (#38)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:5100-5150`
- Test: `tests/unit/test_resolve_imports_export_validation.py`

- [ ] **Step 1: Write test verifying importing non-existent symbol from existing file reports missing symbol error**
- [ ] **Step 2: Implement fix**
In `resolve_imports`, verify that the imported symbol is present in the target module's exported symbol list in `symbols`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(deterministic): validate symbol exports in resolve_imports"`

---

### Task 49: Visual AST Diff for Structural Refactoring (#60)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:6100-6160`
- Test: `tests/unit/test_visual_ast_diff.py`

- [ ] **Step 1: Write test comparing two code versions and classifying changes into rename, reorder, modification**
- [ ] **Step 2: Implement fix**
Add `ast_diff(old_code: str, new_code: str)` returning structural diff tree identifying pure moves/renames vs logic edits.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(ast): add visual AST diff analysis for structural refactorings"`

---

### Task 50: Incremental AST Reparsing on Single-Line Edits (#80)

**Files:**
- Modify: `src/local_ai_hub/code_index.py:2740-2790`
- Test: `tests/unit/test_incremental_ast_reparsing.py`

- [ ] **Step 1: Write test verifying small patch updates only affected symbol nodes without full reindex**
- [ ] **Step 2: Implement fix**
When patch changes a single function, reparse only that function's line range using tree-sitter incremental edit.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(code_index): support incremental AST tree editing for fast single-function updates"`

---

### Task 51: Parameter Normalization in `ast_refactor` (#92)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:2980-3000`
- Test: `tests/unit/test_ast_refactor_parameters.py`

- [ ] **Step 1: Write test verifying `ast_refactor(old_symbol="foo", new_symbol="bar")` passes**
- [ ] **Step 2: Implement fix**
Map `old_symbol` and `new_symbol` directly in `mcp_server.py` without forcing agent to pass new symbol in `diff`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(mcp): normalize old_symbol and new_symbol parameters for ast_refactor"`

---

### Task 52: Cross-Process Cache Invalidation via `PRAGMA data_version` (#100)

**Files:**
- Modify: `src/local_ai_hub/code_index.py:150-190`
- Modify: `src/local_ai_hub/deterministic.py:180-220`
- Test: `tests/unit/test_cross_process_cache_invalidation.py`

- [ ] **Step 1: Write test verifying in-memory cache invalidates when SQLite modified by external connection**
- [ ] **Step 2: Implement fix**
Check `PRAGMA data_version`. If value increments, flush in-memory L1 LRU cache.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(cache): use PRAGMA data_version to invalidate in-memory cache on external SQLite writes"`
