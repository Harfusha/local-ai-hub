# Wave 2 Implementation Plan: Performance & Storage

> **Governing workflow:** Follow [Simplified Worktree and Integration Process](../specs/2026-10-07-simplified-worktree-integration.md). The primary agent implements, reviews, and integrates on current `master`. Subagents and isolated worktrees are optional for independent implementation with disjoint scope; audits and routine work remain with the primary agent. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accelerate database queries by 10x–3000x, eliminate multi-gigabyte disk bloat from dead worktrees, and optimize hot path serialization.

**Architecture:** Modifies `code_index.py`, `deterministic.py`, `artifacts.py`, `preprocess.py`, `rag.py`, `embeddings.py`, `semantic_cache.py`, `sqlite_support.py`, and `json_utils.py`. Introduces direct B-Tree point index columns, replaces Python file I/O with ThreadPool executors, switches string slicing to SQL `substr()`, batches SQLite queries, and activates `orjson`.

**Tech Stack:** SQLite 3 (Indices, VACUUM, PRAGMA), `orjson`, NumPy, ThreadPoolExecutor, Python 3.11+.

---

### Task 19: Direct B-Tree Index for Symbols in `edges` (#81)

**Files:**
- Modify: `src/local_ai_hub/code_index.py:220-250, 3070-3110`
- Test: `tests/unit/test_code_index_edges_query_plan.py`

- [x] **Step 1: Write test verifying EXPLAIN QUERY PLAN uses index on `find_callers` and `find_callees`**

```python
# tests/unit/test_code_index_edges_query_plan.py
import sqlite3
from local_ai_hub.code_index import CodeIndex

def test_find_callers_uses_point_lookup_index(tmp_path):
    idx = CodeIndex({"state_dir": str(tmp_path)})
    with sqlite3.connect(idx.db_path) as con:
        indices = [r[1] for r in con.execute("PRAGMA index_list(edges)").fetchall()]
        assert "idx_edges_dst_name" in indices or "idx_edges_root_kind_dst_name" in indices
```

- [x] **Step 2: Implement fix in `code_index.py`**
1. Add `dst_name TEXT` and `src_name TEXT` columns to `edges` table.
2. Create index: `CREATE INDEX IF NOT EXISTS idx_edges_root_kind_dst_name ON edges(root, kind, dst_name)`.
3. In `find_callers` and `find_callees`, query `WHERE root=? AND kind='calls' AND dst_name=?` instead of `dst LIKE '%/' || sym`.

- [ ] **Step 3: Verify EXPLAIN QUERY PLAN performs point index search**
Run: `python -m pytest tests/unit/test_code_index_edges_query_plan.py -v`

- [ ] **Step 4: Commit**
`git commit -m "perf(code_index): add direct B-tree point index on edges for 3000x faster caller lookups"`

---

### Task 20: Pruning Dead Worktrees & Database Vacuum (#4, #89)

**Files:**
- Modify: `src/local_ai_hub/preprocess.py:450-510`
- Modify: `src/local_ai_hub/code_index.py:2900-2950`
- Modify: `src/local_ai_hub/rag.py:400-430`
- Test: `tests/unit/test_cascading_dead_project_cleanup.py`

- [x] **Step 1: Write test verifying `cleanup_deleted_projects` cascades to `code_index` and `rag`**
- [x] **Step 2: Implement fix**
1. Collect deleted roots: `deleted_roots = [r for r in registered_roots if not Path(r).exists()]`.
2. For each deleted root, call `self.code_index.prune(root)` and `self.rag.remove_workspace(root)`.
3. Add `auto_vacuum = INCREMENTAL` and periodic `PRAGMA incremental_vacuum` to reclaim freelist space.

Source and tmp-path regressions are present, including failed-cascade retry and bounded incremental-vacuum cleanup. Test execution remains deferred until the complete source bundle.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(storage): cascade deleted project cleanup across all index databases and reclaim disk space"`

---

### Task 21: Bounded Source Streaming in `ArtifactStore.get` (#90)

**Files:**
- Modify: `src/local_ai_hub/artifacts.py` (bounded source slice reads)
- Test: `tests/unit/test_artifact_direct_file_slice.py`

- [x] **Step 1: Write tests for bounded, memory-safe artifact slicing**
- [x] **Step 2: Implement bounded source streaming**
Stream only requested bytes/chars from the selected file-backed artifact, preserving UTF-8 and NUL-safe offsets. SQL `substr()` is not the current storage contract; do not materialize an entire large body for a small slice.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(artifacts): use SQLite substr() for zero-copy slicing of large log artifacts"`

---

### Task 22: Fast Mtime/Size Check in `files_needing_reindex` (#84)

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py` (snapshot identity and hash fast path)
- Test: `tests/unit/test_mtime_reindex_check.py`

- [x] **Step 1: Define correctness-preserving fast-path tests**
- [x] **Step 2: Implement fast path with reliable change evidence**
Reuse snapshots only when the persisted file identity matches mtime, size, inode, and platform change time. On Windows, use native NTFS change time; if unavailable, hash the file. Explicit changed hashes force content reads even when metadata is unchanged. Cold-reopen, same-metadata content changes, parser-version invalidation, and batch paths are covered by deferred regressions.

- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(code_index): add mtime and file size pre-check to bypass SHA-256 scans on unchanged files"`

---

### Task 23: Activate `orjson` Fast Serialization Across All Endpoints (#66)

**Files:**
- Modify: `src/local_ai_hub/json_utils.py:10-50`
- Modify: `src/local_ai_hub/app.py:100-140`
- Modify: `src/local_ai_hub/http_server.py:80-120`
- Test: `tests/unit/test_orjson_serialization.py`

- [x] **Step 1: Write test verifying `json_dumps` uses `orjson` when available**
- [x] **Step 2: Implement fix**
Ensure `orjson.dumps(..., option=orjson.OPT_NON_STR_KEYS)` is used in `json_utils.py` and that `http_server.py` and `mcp_server.py` use it consistently.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(serialization): standardize on orjson across all HTTP and MCP JSON boundaries"`

---

### Task 24: Batch Multi-Key Lookup `cache.get_many` in `EmbeddingModel` (#86)

**Files:**
- Modify: `src/local_ai_hub/embeddings.py:670-710`
- Modify: `src/local_ai_hub/cache.py:150-180`
- Test: `tests/unit/test_embedding_batch_cache.py`

- [x] **Step 1: Write test verifying batch lookup performs single SQLite query for multiple keys**
- [x] **Step 2: Implement fix**
Implement `get_many(keys: list[str]) -> dict[str, Any]` in `TieredCache` and `SQLiteCache` using chunked `WHERE key IN (...)`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(embeddings): batch SQLite cache lookups during batch encoding"`

---

### Task 25: SQLite Vector BLOB Representation in `semantic_cache` (#67)

**Files:**
- Modify: `src/local_ai_hub/semantic_cache.py:80-120`
- Test: `tests/unit/test_semantic_cache_blob.py`

- [x] **Step 1: Write test verifying embedding vector stored as raw float32 BLOB**
- [x] **Step 2: Implement fix**
Store vectors as `bytes(np.asarray(vec, dtype=np.float32))` in SQLite BLOB column instead of JSON string. Deserialize via `np.frombuffer` and compute dot product in NumPy matrix.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(semantic_cache): store embeddings as float32 BLOBs and compute similarity in NumPy matrix"`

Source and regression tests integrated; execution remains deferred until the complete source bundle. Existing disposable `semantic_entries` data using the retired vector encoding is dropped and rebuilt; unrelated state tables remain intact.

---

### Task 26: ThreadPool File Reading in `local_ai_repo search` (#69)

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py` (bounded lexical candidate reads)
- Test: `tests/unit/test_parallel_lexical_search.py`

- [x] **Step 1: Write tests for concurrent reads and deterministic result order/content**
- [x] **Step 2: Implement fix**
Use a bounded `ThreadPoolExecutor` to read lexical candidate files concurrently while preserving deterministic results and Windows-safe behavior.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(search): parallelize file reads using ThreadPoolExecutor in lexical search"`

---

### Task 27: Asynchronous Write-Behind in Recovery Journal (#68)

**Files:**
- Modify: `src/local_ai_hub/http_server.py:450-490`
- Test: `tests/unit/test_recovery_journal_write_behind.py`

- [x] **Step 1: Write test verifying recovery journal writes do not block HTTP request latency**
- [x] **Step 2: Implement fix**
Queue recovery journal inserts to a background thread worker with an in-memory queue and batch commit every 100 ms.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(http): introduce async write-behind queue for recovery request journal"`

---

### Task 28: Centroid Filtering for Workspaces with >10k Chunks (#87)

**Files:**
- Modify: `src/local_ai_hub/rag.py:1220-1290`
- Test: `tests/unit/test_rag_centroid_filtering.py`

- [x] **Step 1: Write test for exact default scoring and opt-in centroid pruning**
- [x] **Step 2: Implement fix**
For workspaces exceeding 10,000 chunks, compute k-means cluster centroids. Pre-filter candidate chunks based on closest centroids before running fine-grained scoring.
Centroid pruning remains disabled by default until representative recall validation supports enabling it.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(rag): implement centroid-based candidate filtering for workspaces over 10k chunks"`

---

### Task 29: Index-backed `circular_dependencies` (#21)

**Files:**
- Modify: `src/local_ai_hub/code_index.py` (indexed `edges.kind='imports'` graph)
- Test: `tests/unit/test_circular_dependencies_index_backed.py`

- [x] **Step 1: Write test verifying indexed circular-dependency analysis avoids raw file scans**
- [x] **Step 2: Implement fix**
Use the existing `CodeIndex` import edges (`edges.kind='imports'`) as the source graph; do not rescan or reparse source files during the query.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(dependencies): make circular dependency analysis index-backed"`

---

### Task 30: Depth and Cycle Count Limits in DFS Detector (#25)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:5960-6000`
- Test: `tests/unit/test_dfs_cycle_limits.py`

- [x] **Step 1: Write test with dense cycle graph ensuring bounded execution**
- [x] **Step 2: Implement fix**
Add `max_depth: int = 15` and `max_cycles: int = 50` to `find_circular_dependencies` DFS traversal, preventing infinite loops or lockups on tangled dependency graphs.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "fix(dependencies): cap DFS cycle traversal depth and count to prevent freeze"`

---

### Task 31: Pagination (`offset` & `limit`) in `search` and `code_index` (#22)

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py:2815-2850`
- Modify: `src/local_ai_hub/deterministic.py:4300-4350`
- Test: `tests/unit/test_search_pagination.py`

- [x] **Step 1: Write test retrieving results with `offset=20, limit=20`**
- [x] **Step 2: Implement fix**
Add `offset: int = 0` and `limit: int = 24` to `search` and `code_index` actions in MCP and HTTP servers, returning `has_more: bool` and `total_matches: int`.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(search): add offset and limit pagination to symbol and code search"`

---

### Task 32: Multi-slice Reading in `local_ai_artifact` (#23)

**Files:**
- Modify: `src/local_ai_hub/artifacts.py:260-290`
- Modify: `src/local_ai_hub/mcp_server.py:3920-3940`
- Test: `tests/unit/test_artifact_multi_slice.py`

- [x] **Step 1: Write test passing multiple ranges `slices=[(10, 50), (200, 250)]`**
- [x] **Step 2: Implement fix**
Support `slices: list[dict]` in `local_ai_artifact(action="slice")`, returning all requested sections in a single roundtrip.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(artifact): support batch multi-slice fetching in single MCP call"`

---

### Task 33: L1 In-Memory LRU Cache for Frequent FQN Symbols (#24)

**Files:**
- Modify: `src/local_ai_hub/code_index.py:200-240`
- Test: `tests/unit/test_code_index_l1_lru_cache.py`

- [x] **Step 1: Write test verifying repeated symbol queries hit in-memory LRU without SQLite query**
- [x] **Step 2: Implement fix**
Add `@functools.lru_cache(maxsize=4096)` or custom `OrderedDict` LRU cache for `find_symbol(root, symbol)`. Invalidate when `update_file` is called for that root.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(code_index): add in-memory L1 LRU cache for frequent FQN symbol lookups"`

---

### Task 34: Compound Index on `(root, name, kind)` in Table `facts` (#85)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:240-270`
- Test: `tests/unit/test_deterministic_facts_compound_index.py`

- [x] **Step 1: Write test verifying EXPLAIN QUERY PLAN uses index on `WHERE root=? AND name=?`**
- [x] **Step 2: Implement fix**
Add `CREATE INDEX IF NOT EXISTS idx_facts_root_name_kind ON facts(root, name, kind)` to `deterministic.sqlite3` initialization and migration.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(deterministic): add compound index on facts(root, name, kind)"`

---

### Task 35: Module-Level Regex Pre-compilation in `deterministic.py` (#70)

**Files:**
- Modify: `src/local_ai_hub/deterministic.py:50-100`
- Test: `tests/unit/test_regex_precompilation.py`

- [x] **Step 1: Write test verifying all parsers use pre-compiled module-level regex objects**
- [x] **Step 2: Implement fix**
Move `re.compile(...)` calls from inside loops and function bodies in `deterministic.py` to top-level module constants (`_IMPORT_RE`, `_DEF_RE`, `_CLASS_RE`).
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(deterministic): pre-compile all regexes at module level"`

---

### Task 36: Direct RAG Adaptive CPU Reranker Bypass (#14)

**Files:**
- Modify: `src/local_ai_hub/rag.py:1200-1230`
- Test: `tests/unit/test_rag_direct_cpu_bypass.py`

- [x] **Step 1: Write test verifying `use_reranker=True` degrades gracefully to False on CPU without 66s freeze**
- [x] **Step 2: Implement fix**
In `RAGStore._search_uncached`, check `self.services.reranker.active_device`. If `"cpu"`, bypass cross-encoder scoring and return lexical/dense vector rank directly.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "perf(rag): bypass CPU cross-encoder during direct RAG queries"`

---

### Task 37: SQLite State Directory Hygiene & Backup Rotation (#17)

**Files:**
- Modify: `src/local_ai_hub/sqlite_support.py` (`rotate_database_backups`)
- Test: `tests/unit/test_state_hygiene_backup_rotation.py`

- [x] **Step 1: Write tests verifying bounded durable database backup retention and sidecar cleanup**
- [x] **Step 2: Implement fix**
Rotate snapshots created by the durable database backup path: retain at most three copies, prune expired copies, clean associated WAL/SHM sidecars, and preserve the live database. Do not sweep unrelated `state/` files.
- [ ] **Step 3: Run test and verify pass & Commit**
`git commit -m "feat(storage): implement state directory hygiene and automated backup rotation"`
