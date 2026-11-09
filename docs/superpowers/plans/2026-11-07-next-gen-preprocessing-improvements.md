# Next-Gen Preprocessing Improvements Implementation Plan

## Goal
Implement 5 advanced capabilities for repository preprocessing in Local AI Hub:
1. AST-aware semantic chunking for RAG
2. SQLite Write-Actor / Lock-Free Ingest
3. Precomputed dead code & unused exports in deterministic graph
4. Weighted 2-hop call graph in polyglot demand index
5. Instant fast-path for file watcher (<50 ms)

---

## Task Breakdown

### Task 1: Weighted 2-Hop Call Graph
- **Files**: `src/local_ai_hub/code_index_demand.py`, `tests/test_code_index_2hop_demand.py`
- **Steps**:
  1. Write unit test `tests/test_code_index_2hop_demand.py` testing 2-hop resolution with weights and decay.
  2. Implement `two_hop_related_files` and `two_hop_weighted_files` in `src/local_ai_hub/code_index_demand.py`.
  3. Ensure backward compatibility with `one_hop_related_files`.
  4. Run test to verify passes.

### Task 2: SQLite Write-Actor / Lock-Free Ingest
- **Files**: `src/local_ai_hub/preprocess_write_actor.py`, `src/local_ai_hub/preprocess.py`, `tests/test_preprocess_write_actor.py`
- **Steps**:
  1. Write unit test `tests/test_preprocess_write_actor.py`.
  2. Implement `PreprocessWriteActor` in `src/local_ai_hub/preprocess_write_actor.py`.
  3. Integrate `PreprocessWriteActor` into `PreprocessEngine` in `src/local_ai_hub/preprocess.py` inside `_write_retry`.
  4. Run tests to verify concurrent writes without deadlocks or busy errors.

### Task 3: Precomputed Dead Code & Unused Exports
- **Files**: `src/local_ai_hub/deterministic.py`, `src/local_ai_hub/preprocess.py`, `tests/test_deterministic_dead_code_precompute.py`
- **Steps**:
  1. Write unit test `tests/test_deterministic_dead_code_precompute.py`.
  2. Add `unreferenced_symbols` table to `deterministic.py` canonical DDL.
  3. Implement `precompute_dead_code` and `get_unreferenced_symbols` on `DeterministicEngine`.
  4. Wire `precompute_dead_code` into `_step_deterministic` in `preprocess.py`.
  5. Run tests to verify accurate dead code precomputation.

### Task 4: AST-Aware Semantic Chunking for RAG
- **Files**: `src/local_ai_hub/rag.py`, `tests/test_rag_semantic_chunking.py`
- **Steps**:
  1. Write unit test `tests/test_rag_semantic_chunking.py`.
  2. Enhance Python chunker and brace language chunkers with enclosing context headers.
  3. Run tests to verify code blocks contain parent headers and boundaries.

### Task 5: Instant Fast-Path for File Watcher (<50 ms)
- **Files**: `src/local_ai_hub/preprocess.py`, `tests/test_preprocess_watcher_fast_path.py`
- **Steps**:
  1. Write unit test `tests/test_preprocess_watcher_fast_path.py`.
  2. Implement `fast_update_file` on `PreprocessEngine`.
  3. Verify latency < 50ms and immediate synchronization of ingest cache and deterministic facts.

### Task 6: Full Integration & Release Check
- **Steps**:
  1. Run full test suite for preprocess, code_index, and deterministic.
  2. Run `python -m compileall -q src tools tests`.
  3. Run `python tools/release_check.py --allow-installed`.
