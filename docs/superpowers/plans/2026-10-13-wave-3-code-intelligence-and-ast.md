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

- [x] **Step 1: Write failing test**

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

- [x] **Step 2: Implement fix in `mcp_server.py` and schema**
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

- [x] **Step 1: Write failing test with TypeScript and C# source files**
Verify that chunking a TypeScript file (`.ts`) or C# file (`.cs`) does not split in the middle of a function body when tree-sitter is unavailable.

- [x] **Step 2: Implement fix in `rag.py`**
Implement `_regex_ast_chunks(text: str, language: str) -> list[str]` with regexes matching function/class block declarations (`export class ... {`, `public async Task ... {`, `func ... {`). Split code cleanly at outermost closing braces (`}`) rather than arbitrary character/line counts.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(rag): add AST-aware regex chunker for TS, CS, Go, Rust when tree-sitter is disabled"`

---

### Task 40: Context Line Overlap Deduplication & Merge (#65)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py` (`_exact_evidence`, context slice assembly)
- Test: `tests/unit/test_context_overlap_dedup.py`

- [x] **Step 1: Write source-backed regression tests** for overlapping/nearby ranges, exact line-numbered re-read, consumer integration, and stale-source rejection.
- [x] **Step 2: Implement `merge_overlapping_slices`**
Merge ranges only when path and source SHA-256 match and the next start is at most two lines past the previous end. Confine paths to the requested root, re-read each merged source snapshot, and reject slices whose current hash no longer matches. `_exact_evidence` stores only the merged exact snippet; existing service callers receive the improved context pack through this path, so no service adapter change is needed.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(context): merge overlapping code slices to save 15-30% token budget"`

---

### Task 41: Function Signatures & Type Annotations in FQN Symbols (#64)

**Files:**
- Modify: `src/local_ai_hub/code_index.py:850-900`
- Test: `tests/unit/test_symbol_signatures.py`

- [x] **Step 1: Write test verifying `find_symbol` includes `signature` for TypeScript and Python methods**
- [x] **Step 2: Implement fix**
When indexing symbols in `code_index.py`, extract the full method signature (parameter names, types, return type) using regex or AST, and populate the `signature` column in table `symbols`.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(code_index): extract and store method signatures and return types in symbol index"`

---

### Task 42: Recursive CTE for `traverse_graph` in Agent Memory (#96)

**Files:**
- Modify: `src/local_ai_hub/agent_memory.py:450-490`
- Test: `tests/unit/test_memory_graph_cte.py`

- [x] **Step 1: Write test verifying `traverse_graph` executes single SQL query**
- [x] **Step 2: Implement fix**
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

- [x] **Step 1: Write test verifying tree-sitter runs in worker process without crashing main process on access violation**
- [x] **Step 2: Implement fix**
On Windows Python 3.13, run tree-sitter parsing in a separate pool worker subprocess via IPC. If the worker crashes with an OS access violation, return graceful fallback and keep the main process alive.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(treesitter): isolate tree-sitter parsing in worker process to protect Hub on Windows"`

---

### Task 44: SQLite Parameter Overflow Guard (#99)

**2026-10-15 implementation checkpoint — validation deferred by operator.** Shared `sqlite_batches` limits path/pair batches to 250. Applied to `files_needing_reindex` (now reads only requested files), candidate freshness, parse outcomes, parse/fact blob lookup, test-source links and module facts. Multi-query reads use one read transaction where introduced; module facts retain the global path/line ordering and 120-row cap, stopping once filled. Unbounded kind filters use one JSON1 table parameter, preserving one globally ordered query without a variable per kind. Test-source links are deduplicated and deterministically sorted. The current `batch_replace` method applies source-file replacements rather than generating a bulk SQL IN query; the SQL guards apply to the actual bulk cache/fact paths above.

Deferred regression source: `tests/unit/test_sqlite_parameter_overflow.py` uses temporary SQLite databases with `SQLITE_LIMIT_VARIABLE_NUMBER=512` and 2,000 requested paths/links. The new tests have **not been executed**; no passing, performance or release claim is made. Run them only after the remaining implementation/integration bundle, per the latest user instruction.

Follow-up source review also found the impact resolver's 400-path batches and repeated symbol-name bindings in UNION count queries. Path batches now use the same 250-item helper. Symbol-name membership uses a single JSON1 table parameter for each occurrence, preserving aggregate counts and limits without growing host parameters with symbol count. This follow-up is likewise unexecuted.

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:1200-1240`
- Modify: `src/local_ai_hub/code_index.py:2700-2730`
- Test: `tests/unit/test_sqlite_parameter_overflow.py`

- [x] **Step 1: Write regression source for 2,000 bulk items (execution deferred)**
- [x] **Step 2: Implement fix (source review only; runtime validation pending)**
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

**2026-10-15 implementation checkpoint — validation deferred by operator.** Exact evidence uses the smallest enclosing function/class/type bounds from the symbol index only when its indexed content hash matches the freshly read file bytes. Repeated references to the same full range are deduplicated. Invalid/stale bounds fall back to explicitly non-complete line context. Context packing counts separators, includes whole source blocks only, and returns omitted evidence references when a full block cannot fit; no final character slice cuts a function body. Oversized fact/signature summaries mark truncation. Deferred cases in `tests/unit/test_symbol_context_pack_boundaries.py` cover a 42-line body, duplicate ranges, a 128-character budget and stale indexed hashes. They have **not been run**.

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:2780-2820`
- Test: `tests/unit/test_symbol_context_pack_boundaries.py`

- [x] **Step 1: Write regression source for complete symbol bodies (execution deferred)**
- [x] **Step 2: Implement fix (source reviewed; validation pending)**
Use AST node start and end line bounds from the symbol index instead of fixed +/- 4 line context windows.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(context): expand code context pack slices to full symbol boundaries"`

---

### Task 46: Honest Result Freshness via Mtime Verification (#16)

**2026-10-15 reassessment and implementation — execution deferred.** The existing opt-in content-hash verifier did not cover the default query path: default and cached queries reported `not_checked`, yet their score could reach 0.925. Default queries now compare each returned file's indexed nanosecond mtime and size, including cache hits. `stat_current_candidates` explicitly distinguishes metadata agreement from content-hash proof; `verify_freshness=True` retains the stronger content check. Stale results carry `stale=true` and confidence at most 0.50; metadata-current results are capped at 0.90. Unknown freshness remains explicit. No source bodies are read by the default stat check.

The app wires stale candidates to the existing preprocessor's `notify_path_changed`, which coalesces owning registered projects and respects background/paused controls. Notifications are additionally bounded by a 512-entry, 30-second cache; notification acceptance does not prove reindex completion. Deferred temporary-database cases cover cached-query freshness and same-size edits with restored mtime. Tests, runtime scheduling and latency remain unexecuted until the complete bundle gate.

**Files:**
- Modify: `src/local_ai_hub/code_index.py:1180-1220`
- Test: `tests/unit/test_code_index_freshness_check.py`

- [x] **Step 1: Write stale cached-query and hash-verification regression source (execution deferred)**
- [x] **Step 2: Implement freshness checks and existing-queue notifications (validation pending)**
Before returning `confidence: 0.925`, inspect file `mtime`. If changed, mark result as `stale: True` and trigger background reindex.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(code_index): check file mtime before returning high-confidence search results"`

---

### Task 47: AST Skeletonize Directly from Code Index (#34)

**2026-10-15 implementation checkpoint — source review only, tests deferred.** `local_ai_repo(action="skeletonize", root=ABS_ROOT, path=FILE)` with no inline source routes to a bounded indexed symbol outline through the existing HTTP action. Root/path containment, project path policy and indexed mtime/size are checked; metadata is rechecked after the query. No source text is read or reparsed. Missing/stale indexes fail explicitly rather than silently loading source. The outline is capped at 2,000 symbols/64,000 characters, marks truncation and declares omitted imports/decorators/docstrings/bodies. Existing inline-source skeletonization retains its behavior, including its existing path-as-target convention. Retaining selected function bodies requires explicit inline source. Deferred regression source: `tests/unit/test_skeletonize_from_index.py`; not executed.

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:7320-7360`
- Test: `tests/unit/test_skeletonize_from_index.py`

- [x] **Step 1: Write regression source forbidding source reads (execution deferred)**
- [x] **Step 2: Implement fix (source reviewed; validation pending)**
In `skeletonize_code`, if `path` is registered, construct the skeleton directly from table `symbols` (classes, functions, signatures) without reading and parsing the file.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(ast): construct file skeleton directly from indexed symbols"`

---

### Task 48: Static Export Validation in `resolve_imports` (#38)

**2026-10-15 implementation checkpoint — execution deferred.** The actual API accepts unresolved symbol names and suggests imports; it does not accept an existing import statement or target module. Previously it selected the first case-insensitive declaration, including nested symbols, without export/freshness verification. It now selects up to 16 exact-case indexed candidates per symbol, joins current indexed file hashes, checks root/path/project policy, and verifies bounded current snapshots outside the SQLite lock before suggesting imports. Requests are capped at 64 symbols; retained source is capped at 4 MB. Stale and unproven candidates are returned with explicit reasons. The service bypasses its workspace-only result cache so hash proof is renewed on each call.

Static checks cover Python top-level class/function declarations (named imports correctly do not use `__all__`), JS/TS direct named exports and locally declared named-export lists, and indexed accessible namespace-level C#/PHP types. Default-only exports cannot become named-import suggestions. JS regex/division ambiguity, re-exports requiring target proof, unsupported source forms and nested members are conservatively unresolved rather than certified. This is current indexed-candidate static proof, not module execution, full language export enumeration or proof of successful runtime import. Namespace import construction reuses the bounded verified snapshot instead of a second unbounded source read. MCP preserves the rejection/validation fields. Deferred cases cover missing names in existing modules, stale declarations, nested methods, explicit and default exports, aliases, comments/strings and opaque regex cases. No tests/imports/builds were executed.

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:5100-5150`
- Test: `tests/unit/test_resolve_imports_export_validation.py`

- [x] **Step 1: Write missing/stale/non-exported symbol regression source (execution deferred)**
- [x] **Step 2: Implement bounded current-source export verification (validation pending)**
In `resolve_imports`, verify that the imported symbol is present in the target module's exported symbol list in `symbols`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(deterministic): validate symbol exports in resolve_imports"`

---

### Task 49: Visual AST Diff for Structural Refactoring (#60)

**2026-10-15 source implementation — no execution/validation yet.** Added bounded Python `ast_diff(old_code,new_code)` in a dedicated module, exposed through `DeterministicEngine.ast_diff` and the existing `semantic_diff` MCP/HTTP path. The explicit source-pair fields are action-scoped; omission retains the existing call-graph diff. Matching uses exact own-structure fingerprints under qualified identities and unique rename fingerprints, excluding nested definitions from their parent's own-logic fingerprint. Reordering compares surviving siblings so insertion alone does not invent moves. Duplicate/ambiguous correspondences remain conservative additions/removals. Results include source hashes, locations, change counts and a qualified-scope tree; `behavior_equivalence_proven` is always false. Module-level edits remain visible.

Inputs are capped at 1 MiB UTF-8 each, 20,000 AST nodes, AST depth 128, definition depth 32 and 1,000 definitions per side. The shared HTTP daemon stores the full result in a tenant-scoped artifact and returns a bounded preview (up to 32 changes/8,000 preview characters). Syntax/limit and artifact-storage failures remain explicit. INSTALL/UPDATE prompts match. Deferred sources: `tests/unit/test_visual_ast_diff.py` and `tests/unit/test_mcp_structural_ast_diff.py`; neither has run. Current source comparison is Python-specific; do not infer TypeScript/C#/Go/Rust AST-diff coverage or live HTTP/MCP correctness from this implementation checkpoint.

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:6100-6160`
- Test: `tests/unit/test_visual_ast_diff.py`

- [x] **Step 1: Write classification/transport regression source (execution deferred)**
- [x] **Step 2: Implement Python structural path (source reviewed; validation pending)**
Add `ast_diff(old_code: str, new_code: str)` returning structural diff tree identifying pure moves/renames vs logic edits.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(ast): add visual AST diff analysis for structural refactorings"`

---

### Task 50: Incremental AST Reparsing on Single-Line Edits (#80)

**2026-10-15 implementation checkpoint — all execution deferred until the remaining bundle is implemented.** CodeIndex now supplies a database/root/path/analyzer identity to the existing parser. A worker-local LRU retains up to 32 native Trees, with 8 MiB of retained source bytes and a 2 MiB per-source admission limit (these limits do not measure native Tree RAM). UTF-8 byte edits use `Tree.edit` and `Parser.parse(source, old_tree)`; failed incremental parses discard the edited Tree and fall back to a full parse. Native parser access and extraction remain serialized, and Windows Python 3.13 keeps the existing subprocess isolation. Workers retain initialized parsers between requests; timeout/crash cleanup terminates only owned worker handles with bounded joins and reports whether cleanup was confirmed. API reference: https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.Tree.html .

Single-file updates, including one-file watcher batches, compare metadata tuples inside the SQLite write transaction, retain identical symbol/reference/edge rows, and delete/insert only changed occurrences. Duplicate reference multiplicity is preserved; symbol conflicts follow the existing last-occurrence primary-key behavior. Larger initial batches retain the existing bulk SQL path. Extraction still walks the resulting Tree; this is native incremental parsing plus metadata delta writes, not proof that all extraction work is limited to changed lines. Diagnostics distinguish actual incremental parses from fallback parsers. Deferred regression source covers UTF-8 byte edits, Tree identity reuse and SQLite row preservation using `:memory:`; it has not been executed. Native-library behavior, performance and Windows cleanup remain pending the final bundle gate.

**Files:**
- Modify: `src/local_ai_hub/code_index.py:2740-2790`
- Test: `tests/unit/test_incremental_ast_reparsing.py`

- [x] **Step 1: Write incremental-edit and unchanged-row regression source (execution deferred)**
- [x] **Step 2: Implement incremental Tree reuse and metadata delta writes (validation pending)**
When patch changes a single function, reparse only that function's line range using tree-sitter incremental edit.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(code_index): support incremental AST tree editing for fast single-function updates"`

---

### Task 51: Parameter Normalization in `ast_refactor` (#92)

**2026-10-15 reassessment and implementation — validation deferred.** The previous adapter still required `query/task` and `diff`; explicit symbols were absent from both MCP signatures and the generated contract. Added keyword-only nullable `old_symbol`/`new_symbol` through both wrapper layers, scoped to `ast_refactor` in the contract. Explicit values win; omission preserves existing mappings, while explicitly empty/invalid names fail before HTTP dispatch. Both names are bounded to 512 characters and reject null bytes. Existing HTTP rename/apply semantics are unchanged. INSTALL/UPDATE prompts match. Deferred MCP-wire and precedence cases: `tests/unit/test_ast_refactor_parameters.py`, not executed.

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:2980-3000`
- Test: `tests/unit/test_ast_refactor_parameters.py`

- [x] **Step 1: Write explicit-symbol/precedence regression source (execution deferred)**
- [x] **Step 2: Implement fix (source reviewed; validation pending)**
Map `old_symbol` and `new_symbol` directly in `mcp_server.py` without forcing agent to pass new symbol in `diff`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(mcp): normalize old_symbol and new_symbol parameters for ast_refactor"`

---

### Task 52: Cross-Process Cache Invalidation via `PRAGMA data_version` (#100)

**2026-10-15 implementation checkpoint — validation deferred by operator.** Added a lazy persistent read-only `SQLiteChangeObserver` with 50-ms SQLite waits, file-identity replacement detection, explicit close and a connection finalizer. Comparing `data_version` across short-lived connections would not work; each observer retains its connection. Unknown observer state bypasses cache reuse. CodeIndex clears query/impact/path/count/status caches and advances existing generation keys; in-flight impact subcaches retain the starting generation. Its observer guard is separate from the long indexing lock so status does not newly wait for an indexing transaction.

Deterministic source-table INSERT/UPDATE/DELETE triggers advance affected root generations and invalidate L2 rows, including raw external writes and root changes. Query-cache writes check the source generation in a write transaction before storing and acknowledge cache-only observer changes, preserving L1 reuse. First installation of the invalidation triggers discards old derived L2 query rows. `LocalAIApp.close()` closes both observers; no production database was opened or changed during this source edit. Deferred source `tests/unit/test_cross_process_cache_invalidation.py` covers another Python process, L1 invalidation, both deterministic cache tiers and stale-result fencing. It has **not been executed**. Windows handle release, trigger behavior, races and cache performance remain acceptance work; no release claim follows.

**Files:**
- Modify: `src/local_ai_hub/code_index.py:150-190`
- Modify: `src/local_ai_hub/deterministic.py:180-220`
- Test: `tests/unit/test_cross_process_cache_invalidation.py`

- [x] **Step 1: Write external-process/cache-tier regression source (execution deferred)**
- [x] **Step 2: Implement fix (source reviewed; validation pending)**
Check `PRAGMA data_version`. If value increments, flush in-memory L1 LRU cache.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(cache): use PRAGMA data_version to invalidate in-memory cache on external SQLite writes"`
