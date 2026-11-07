# Next-Gen Preprocessing Improvements Design Specification

## Overview
This specification details 5 advanced capabilities for Local AI Hub's repository preprocessing engine:
1. **AST-Aware Semantic Chunking for RAG**: Chunk code along function/class/method boundaries with inherited parent signatures (class headers, docstrings) instead of character sliding windows.
2. **SQLite Write-Actor / Lock-Free Ingest**: Dedicated single-writer thread with transaction batching to eliminate database lock contention across multi-threaded CPU worker phases.
3. **Precomputed Dead Code & Unused Exports**: Precompute unreferenced functions, classes, and export symbols during deterministic graph processing, persisted in `unreferenced_symbols`.
4. **Weighted 2-Hop Call Graph**: Extend demand-driven dependency indexing in `code_index_demand.py` to a 2-hop traversal with interface/base class weighting and distance decay.
5. **Instant Fast-Path for File Watcher (<50 ms)**: Dedicated single-file update path updating ingest cache, deterministic AST facts, and symbol indices without triggering the full 13-phase loop.

---

## Architecture & Component Design

### 1. AST-Aware Semantic Chunking (`rag.py`)
- **Problem**: When classes/methods exceed the chunk budget, naive character/paragraph chunking severs method definitions from their class context, leading to loss of semantic coherence in RAG embeddings.
- **Solution**:
  - Python AST Chunker: Split large classes into individual methods, each prefixed with class declaration context (`class Foo:\n    # method bar\n...`). For oversized functions, chunk along statement blocks (loops, try-except, top-level branch blocks) retaining function signature.
  - Multi-language AST/Lexical: Extend `_ast_chunks` and `_regex_ast_chunks` for brace languages (TypeScript, JavaScript, C#, Go, Rust, Java, C/C++, PHP). Subdivide classes/interfaces at method boundaries and prepend the enclosing type header.
  - Compatibility: Adheres to single-owner release contract and retains chunker version tracking (`RAG_CHUNKER_VERSION`).

### 2. SQLite Write-Actor (`preprocess_write_actor.py` & `preprocess.py`)
- **Problem**: Multi-threaded CPU phases (`_step_inventory`, `_step_hash`, `_step_deterministic`) repeatedly open short-lived SQLite connections with `BEGIN IMMEDIATE` and `self._db_lock`, resulting in `busy` retry backoffs when workers collide.
- **Solution**:
  - `PreprocessWriteActor`: Thread-safe worker queue processing `WriteTask(operation, future)`.
  - Holds an open connection with WAL mode.
  - Batches pending write operations inside a single transaction: commits when the queue drains or after batch limit (e.g. 50 tasks).
  - Graceful fallback: Synchronous direct execution if actor is stopped or during test teardown.

### 3. Precomputed Dead Code & Unused Exports (`deterministic.py`)
- **Problem**: Dead code queries (`detect_dead_code`) perform full-table scans on `symbols` and `refs` at query time.
- **Solution**:
  - Add canonical table `unreferenced_symbols` in `deterministic.sqlite3`:
    ```sql
    CREATE TABLE IF NOT EXISTS unreferenced_symbols(
      root TEXT NOT NULL,
      path TEXT NOT NULL,
      name TEXT NOT NULL,
      kind TEXT NOT NULL,
      line INTEGER NOT NULL DEFAULT 0,
      updated_at REAL NOT NULL,
      PRIMARY KEY(root, path, name)
    );
    CREATE INDEX IF NOT EXISTS idx_unref_sym_root ON unreferenced_symbols(root);
    ```
  - `precompute_dead_code(root: str, limit: int = 500)`: Evaluates zero-incoming reference symbols across the project graph and writes them to `unreferenced_symbols`.
  - Exposed via `get_unreferenced_symbols(root: str, limit: int = 50)` for instant sub-millisecond retrieval.
  - Automatically triggered in `_step_deterministic` when file processing completes.

### 4. Weighted 2-Hop Call Graph (`code_index_demand.py`)
- **Problem**: 1-hop demand indexing misses critical inherited interfaces, base classes, and immediate caller/callee context that spans two hops.
- **Solution**:
  - `two_hop_related_files(root: Path, seeds: list[str], eligible: set[str], repo_tools: Any, *, limit: int = 64, hop1_limit: int = 32, decay: float = 0.5) -> list[str]`.
  - First hop extracts direct imports (weight 1.0). Interfaces and base classes receive a 1.5x weight multiplier based on symbol naming patterns (`I[A-Z]`, `*Interface`, `*Base`, `abstract`).
  - Second hop extracts transitive imports for top-scoring hop-1 files, weighted by `hop1_score * decay`.
  - Returns deduplicated files ranked by total composite score.

### 5. Instant Fast-Path for File Watcher (`preprocess.py`)
- **Problem**: Saving a single file currently resets project phase to `inventory` and enqueues a full 13-phase scan.
- **Solution**:
  - `fast_update_file(root: str, rel_path: str, content: str | None = None) -> dict[str, Any]`.
  - 1. Ingest cache update: Loads or receives content, updates RAM snapshot & AST.
  - 2. Direct metadata update: Updates `file_refs` row (`content_hash`, `mtime_ns`, `size`) via write-actor.
  - 3. Incremental deterministic update: Calls `deterministic.update_file(root, rel_path, content_hash)` for instant AST facts.
  - 4. Incremental code index update: Calls `code_index.update_file(root, rel_path)` if configured.
  - 5. Target latency: < 50 ms. Does not disturb project background status or queue full cycles.

---

## Verification & Quality Gate
- Unit tests for each capability:
  1. `tests/test_rag_semantic_chunking.py`
  2. `tests/test_preprocess_write_actor.py`
  3. `tests/test_deterministic_dead_code_precompute.py`
  4. `tests/test_code_index_2hop_demand.py`
  5. `tests/test_preprocess_watcher_fast_path.py`
- Integration regression: All existing preprocess, code_index, and deterministic test suites pass.
- Release verification: `python tools/release_check.py --allow-installed` clean.
