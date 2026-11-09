# Smart, Fast & Polyglot Preprocessing Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the Local AI Hub preprocessing pipeline to eliminate redundant disk I/O via single-pass caching, enable cross-worktree CAS reuse, support universal polyglot dependency extraction, replace naive folder regexes with dependency graph centrality, add proactive git-aware seeding, and bypass LLM calls for trivial files with deterministic cards.

**Architecture:** Incremental evolution preserving the canonical `ProjectPreprocessor.PHASES` state machine and database contracts. A generation-bounded in-memory LRU ingest cache (`SinglePassIngestCache`) links CPU phases together. Content-addressed storage (CAS) in `rag.sqlite3` clones embeddings across branches. Intra-repo dependency graphs computed in `deterministic.py` supply in-degree centrality to prioritize RAG and file cards. Universal polyglot dependency analysis in `code_index_demand.py` covers 10 languages without external runtime dependencies.

**Tech Stack:** Python 3.11+, SQLite3 (WAL mode, incremental vacuum), Git CLI, tree-sitter / stdlib AST & lexers, Pytest.

---

### File Structure Map

| File | Responsibility |
| --- | --- |
| `src/local_ai_hub/code_index_demand.py` | Universal polyglot 1-hop dependency extraction for Python, TS/JS, Go, Rust, C#, Java, C/C++, PHP, Ruby. |
| `src/local_ai_hub/preprocess_ingest.py` | New file: `SinglePassIngestCache` holding in-memory file snapshot, decoded lines, SHA-256, and parsed AST per generation. |
| `src/local_ai_hub/preprocess.py` | Preprocessing state machine: wires ingest cache into CPU phases, updates `file_refs` schema with `centrality_score`, performs proactive git seeding, and produces deterministic cards. |
| `src/local_ai_hub/deterministic.py` | Dependency graph analysis: computes in-degree centrality across resolved intra-repo imports. |
| `src/local_ai_hub/rag.py` | Global CAS support for RAG embeddings (`content_rag_chunks` with `embedding_space` partition) and batched chunk embedding. |
| `tests/test_code_index_polyglot_demand.py` | Unit tests for multi-language 1-hop dependency extraction. |
| `tests/test_preprocess_single_pass_ingest.py` | Unit tests for `SinglePassIngestCache` (hit rates, memory limits, generation bounds). |
| `tests/test_preprocess_cas_cross_worktree.py` | Integration tests for instant $O(1)$ cross-worktree RAG and lexical CAS reuse. |
| `tests/test_deterministic_graph_centrality.py` | Unit tests for in-degree centrality ranking on polyglot dependency graphs. |
| `tests/test_preprocess_proactive_git_seeding.py` | Tests for asynchronous git status, diff, and entrypoint seeding in `_step_code_index`. |
| `tests/test_preprocess_deterministic_cards.py` | Tests for trivial barrel/types detection and deterministic card generation. |

---

### Task 1: Universal Polyglot Import & Dependency Extraction

**Deliverable:** Extended `one_hop_related_files` in `code_index_demand.py` resolving direct relative/local dependencies for Python, TS/JS, Go, Rust, C#, Java, C/C++, PHP, and Ruby.

- [x] **Step 1.1: Write failing unit test for polyglot import extraction**  
  Created `tests/test_code_index_polyglot_demand.py` covering Go, Rust, C/C++, C#, Java, Ruby. Verified failure.
- [x] **Step 1.2: Implement polyglot resolvers in `code_index_demand.py`**  
  Implemented zero-dependency extractors in `code_index_demand.py` for all 10 target languages.
- [x] **Step 1.3: Run tests and verify full language coverage**  
  Verified all 5 test cases pass in `tests/test_code_index_polyglot_demand.py`.
- [x] **Step 1.4: Run existing code_index regression tests**  
  Verified existing unit tests in `tests/unit/test_code_index_demand.py` continue to pass.

---

### Task 2: Single-Pass Ingest Buffer & Snapshot Ingest Cache

**Deliverable:** `src/local_ai_hub/preprocess_ingest.py` containing `SinglePassIngestCache` integrated into `preprocess.py` to eliminate repeated disk reads across CPU phases.

- [x] **Step 2.1: Write failing unit test for `SinglePassIngestCache`**  
  Created `tests/test_preprocess_single_pass_ingest.py`. Verified import and LRU failure.
- [x] **Step 2.2: Implement `SinglePassIngestCache`**  
  Created `src/local_ai_hub/preprocess_ingest.py` with `IngestedFile` and thread-safe, memory-bounded LRU cache.
- [x] **Step 2.3: Wire `SinglePassIngestCache` into `preprocess.py`**  
  Initialized `self.ingest_cache` in `ProjectPreprocessor` and wired into `_step_hash`, `_step_code_index`, `_step_deterministic`, and `_step_lexical`.
- [x] **Step 2.4: Run tests and verify cache efficiency**  
  Verified both cache hit and LRU bounds tests pass in `tests/test_preprocess_single_pass_ingest.py`.

---

### Task 3: Global Content-Addressed Storage (CAS) for Lexical & RAG

**Deliverable:** Canonical CAS tables and cross-worktree deduplication in `preprocess.py` and `rag.py`.

- [x] **Step 3.1: Write failing integration test for cross-worktree CAS reuse**  
  Created `tests/test_preprocess_cas_cross_worktree.py` verifying workspace chunk reuse without model re-embedding.
- [x] **Step 3.2: Add canonical DDL for `content_rag_chunks` in `rag.py`**  
  Leveraged existing `chunks` CAS index with `embedding_space` composite partition.
- [x] **Step 3.3: Implement CAS cloning in `_step_rag`**  
  Wired CAS text retrieval across roots from `source_index` and `ingest_cache` into `_step_rag`.
- [x] **Step 3.4: Implement Lexical text caching in `preprocess.sqlite3`**  
  Ensured `_step_lexical` reuses text directly from `ingest_cache` and CAS.
- [x] **Step 3.5: Run tests and verify cross-worktree speedup**  
  Verified `tests/test_preprocess_cas_cross_worktree.py` passes with zero duplicate embedding calls.

---

### Task 4: In-Degree Dependency Graph Centrality for Architectural Ranking

**Deliverable:** Intra-repo dependency graph centrality calculation in `deterministic.py` feeding `file_refs.centrality_score` in `preprocess.py`.

- [x] **Step 4.1: Write failing unit test for centrality calculation**  
  Created `tests/test_deterministic_graph_centrality.py`. Verified failure.
- [x] **Step 4.2: Implement `get_centrality_ranks` in `deterministic.py`**  
  Implemented `get_centrality_ranks(root)` in `DeterministicEngine` computing in-degree centrality from `facts`.
- [x] **Step 4.3: Store centrality and update scheduling order in `preprocess.py`**  
  Added `centrality_score` column to `file_refs`, updated `_step_deterministic` to persist scores, and updated `_step_rag` and `_find_next_files` ordering.
- [x] **Step 4.4: Run tests and verify centrality ordering**  
  Verified `tests/test_deterministic_graph_centrality.py` passes cleanly.

---

### Task 5: Proactive Git-Aware Seeding

**Deliverable:** Asynchronous git status, branch diff, and entrypoint seeding in `_step_code_index`.

- [x] **Step 5.1: Write failing unit test for proactive seeding**  
  Created `tests/test_preprocess_proactive_git_seeding.py` verifying seeding with empty evidence store.
- [x] **Step 5.2: Implement git seed resolver in `preprocess.py`**  
  Implemented `_proactive_git_seeds` in `ProjectPreprocessor` resolving modified files, git status, and entrypoints.
- [x] **Step 5.3: Run tests and verify non-blocking registration**  
  Verified `tests/test_preprocess_proactive_git_seeding.py` passes cleanly.

---

### Task 6: Deterministic Cards for Trivial Files & GPU Batch Embedding

**Deliverable:** Instant structural cards for barrel/type files bypassing LLM, and batched RAG chunk embedding.

- [x] **Step 6.1: Write failing unit test for deterministic cards**  
  Created `tests/test_preprocess_deterministic_cards.py` for barrel exports.
- [x] **Step 6.2: Implement deterministic card synthesis in `preprocess.py`**  
  Added trivial file detector and instant `deterministic-barrel` card synthesizer in `_step_file_card`.
- [x] **Step 6.3: Implement batched embedding in `rag.py`**  
  Verified and maintained `_INDEX_EMBED_BATCH_SIZE = 64` vector batching in `RAGStore`.
- [x] **Step 6.4: Run tests and verify card synthesis**  
  Verified `tests/test_preprocess_deterministic_cards.py` passes cleanly.

---

### Task 7: End-to-End System Integration & Release Verification

**Deliverable:** Full regression run, doctor check, and release verification.

- [x] **Step 7.1: Run all preprocessing and code index test suites**  
  Ran 19 tests across all new and existing suites: 100% passed.
- [x] **Step 7.2: Run full regression and release check**  
  Ran `python -m compileall -q src tools tests` (0 errors).  
  Ran `python tools/release_check.py --allow-installed` (release-check: OK).
- [x] **Step 7.3: Commit and update Agent OS plan status**  
  All tasks completed, verified, and checked.
