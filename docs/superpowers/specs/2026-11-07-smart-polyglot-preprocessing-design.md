# Smart, Fast & Polyglot Preprocessing Pipeline Design

**Date:** 2026-11-07  
**Status:** Approved by Builder Review / Ready for Implementation  
**Author:** Pair programming (Antigravity & User)  
**Target:** Local AI Hub (`src/local_ai_hub/preprocess.py`, `code_index.py`, `deterministic.py`, `rag.py`)

---

## 1. Intent and Why

The Local AI Hub preprocessing pipeline prepares repository intelligence for coding agents. In its current implementation, it suffers from several structural inefficiencies:
1. **Redundant Disk I/O:** The same file is read from disk 4 to 5 separate times across sequential phases (`hash`, `code_index`, `deterministic`, `lexical`, `rag`, `files`).
2. **Duplicated AST Parsing:** `code_index_demand.py` parses Python/JS files for import extraction, and `deterministic.py` subsequently re-parses the same files for symbols and call graphs.
3. **Missing Cross-Worktree CAS Reuse:** While semantic `content_cards` are reused by content hash, `source_fts` (lexical full-text), `deterministic.sqlite3` facts, and `rag` vector embeddings are bound to `root`. Registering a new git worktree or branch with 95%+ identical files re-runs expensive indexing and embedding.
4. **Heuristic/Regex Architectural Ranking:** Phase scheduling prioritizes files using naive path regexes (`/Controllers/`, `/Services/`, `/Core/`), failing on non-standard frameworks or languages.
5. **Restricted Demand Indexing:** `code_index` demand admission only understands Python, JS/TS, and basic PHP regexes, leaving Go, Rust, C#, Java, C/C++, and Ruby unindexed until manually forced.
6. **Sequential Execution Bottlenecks:** Single-item RAG embeddings and LLM card synthesis for trivial files (barrel exports, typings, configs) consume unnecessary GPU resources.

The goal of this project is to eliminate redundant work, drastically increase throughput, enhance intelligence via dependency graph centrality, and make the preprocessing engine universal across any programming language.

---

## 2. Goals, Non-Goals, Anti-Goals

### Goals
- **Single-Pass Ingest Buffer (`SinglePassIngestCache`):** Read a file once per batch; compute SHA-256, parse AST/syntax, and extract text representations into an ephemeral in-memory cache shared across concurrent microsteps.
- **Global Content-Addressed Storage (CAS):** Persist deterministic facts, lexical FTS tokens, and RAG embeddings keyed by `content_hash`. New worktrees or branches with identical content hashes achieve $O(1)$ instantaneous linking without re-reading or re-embedding.
- **Universal Polyglot Import & Dependency Extraction:** Support Python, TypeScript, JavaScript, Go, Rust, C#, Java, C/C++, PHP, and Ruby for 1-hop demand indexing in `code_index_demand.py`.
- **Topological Graph Centrality (In-Degree / PageRank):** Replace path regexes with in-degree dependency centrality computed during the deterministic phase. Modules with the highest inbound dependency count are recognized as the architectural core and prioritized for RAG and file cards.
- **Proactive Git-Aware Seeding:** On project registration or branch change, proactively seed `code_index` using uncommitted working tree changes (`git status`), commits ahead of the base branch (`git diff`), repository entrypoints, and their 1-hop dependencies.
- **Deterministic Cards for Trivial Files:** Detect barrel exports (`index.ts`, `__init__.py`), type declarations, and configuration files, generating instant structural cards without invoking the LLM.
- **GPU Batch Embedding:** Vectorize RAG embedding generation in batches of 32–64 chunks.

### Non-Goals
- Altering the public MCP schema or breaking existing tools (`local_ai_repo:search`, `code_index`, `deterministic`, `rag`).
- Altering external managed backends (e.g., Serena LSP integration).
- Changing the visible sequence of `ProjectPreprocessor.PHASES` (`inventory`, `hash`, `code_index`, `deterministic`, `serena`, `lexical`, `rag`, `files`, `modules`, `project`, `hot_queries`, `diagnostics`, `complete`), preserving full backward compatibility with the dashboard, status endpoints, and existing tests.

### Anti-Goals
- Unbounded memory consumption: Ingest caches must be strictly bounded with LRU eviction and generation fences.
- Fragile SQLite migrations: CAS tables must be designed into canonical DDL to avoid runtime `ALTER TABLE`, table locking, or breaking existing single-root databases.

---

## 3. Approaches Considered

### Approach A: Incremental Pipeline Evolution with In-Memory Ingest & Global CAS (Selected)
- Preserves the canonical `PHASES` state machine and database contracts.
- Introduces `SinglePassIngestCache` integrated with `RepositoryTools` snapshot caching to share in-memory file buffers and parsed ASTs between phases.
- Extends `code_index_demand.py` into a polyglot dependency resolver.
- Replaces folder regexes with in-degree graph centrality computed from the deterministic graph.
- Introduces content-addressed reuse for lexical FTS and RAG embeddings.
- **Pros:** 100% backward compatibility with existing tests, dashboard UI, and MCP clients; low regression risk; immediate performance gains.
- **Cons:** Requires coordinating cache lifecycles across phase steps.

### Approach B: Streaming DAG Execution Engine (Rejected)
- Rewrites preprocessing as an asynchronous stream where each file flows from ingest directly through hashing, AST, FTS, RAG, and card generation.
- **Pros:** Lowest theoretical latency for single files.
- **Cons:** Breaks phase tracking in the dashboard, alters SQLite schema contracts, and breaks dozens of existing integration tests.

### Approach C: Isolated CAS & Polyglot Patch (Rejected)
- Only patches `code_index_demand.py` and adds cross-worktree CAS tables, leaving phase I/O separate.
- **Pros:** Minimal touch surface.
- **Cons:** Leaves 4x redundant disk I/O and naive regex scheduling unresolved.

---

## 4. Detailed Component Design & Architecture Decisions

### 4.1. Single-Pass Ingest Cache (`src/local_ai_hub/preprocess_ingest.py`)
- **Lifecycle & Memory Bounds:**
  - Integrated with `RepositoryTools` snapshot caching as a generation-bounded LRU cache (capped at 500 files or 64 MB RAM).
  - During phase execution (`hash` -> `code_index` -> `deterministic` -> `lexical`), when a file is read, its decoded UTF-8 lines, content hash, and AST parse tree are retained in the ingest cache.
  - Subsequent phases read directly from the in-memory cache rather than hitting the disk again.
  - Stale entries are evicted on generation bump or via `notify_path_changed`.
  ```python
  class IngestedFile:
      path: str
      content_hash: str
      size_bytes: int
      text: str
      lines: tuple[str, ...]
      ast_tree: Any | None
      imports: tuple[str, ...]

  class SinglePassIngestCache:
      def get_or_ingest(self, root: Path, rel_path: str) -> IngestedFile: ...
  ```

### 4.2. Universal Polyglot Dependency Resolver (`code_index_demand.py`)
- Extends one-hop import resolution with zero-external-dependency robust regex/AST extractors:
  - **Python:** `ast.parse` (Import / ImportFrom)
  - **JS / TS:** Regex/lexer for static and dynamic `import`, `require`, and `export ... from`
  - **Go:** `import (...)` blocks and single imports, mapping module paths against local `go.mod`
  - **Rust:** `mod <name>;` and `use crate::<name>;`
  - **C / C++:** `#include "local_header.h"`
  - **C#:** `using <Namespace>;` mapped to project namespace folder hierarchies
  - **Java:** `import package.class;` mapped to source root directories
  - **PHP:** `require`, `include`, `use` statements
  - **Ruby:** `require_relative '<path>'`

### 4.3. Global Content-Addressed Storage (CAS) for FTS & RAG
- **Physical DB Location & DDL:**
  - **Lexical CAS:** Handled in `preprocess.sqlite3` via `content_lexical(content_hash TEXT PRIMARY KEY, text TEXT, updated_at REAL)`. Lexical phase reuses this text instead of re-reading from disk; `source_fts` continues indexing into its root-scoped FTS5 table with zero disk reads.
  - **RAG CAS:** Defined in `rag.sqlite3` via canonical startup DDL:
    ```sql
    CREATE TABLE IF NOT EXISTS content_rag_chunks (
        content_hash TEXT NOT NULL,
        embedding_space TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        chunk_text TEXT NOT NULL,
        embedding_blob BLOB NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (content_hash, embedding_space, chunk_index)
    );
    CREATE INDEX IF NOT EXISTS idx_content_rag_lookup
    ON content_rag_chunks(content_hash, embedding_space);
    ```
  - `embedding_space` stores `f"{model_name}:{dimension}:{vector_revision}"`. If a file has the same `content_hash` and `embedding_space`, its embeddings are cloned into the project workspace in SQLite in $O(1)$ without GPU inference.

### 4.4. Dependency Graph Centrality
- **Computation & Boundary Isolation:**
  - Inside `deterministic.py`, `DeterministicEngine` analyzes all intra-repo imports and computes in-degree centrality per file:
    $$\text{centrality}(f) = |\{src \mid src \text{ imports } f\}|$$
  - Exposes `get_centrality_ranks(root) -> dict[str, float]`.
  - In `preprocess.py`, `_step_deterministic` queries `get_centrality_ranks(root)` and batch-updates `file_refs.centrality_score` in `preprocess.sqlite3`. This maintains strict database ownership boundaries.
  - `_find_next_files` and `_step_rag` order pending files by:
    `ORDER BY (COALESCE(last_accessed_at, 0) > 0) DESC, COALESCE(centrality_score, 0) DESC, size ASC, path ASC`

### 4.5. Proactive Git-Aware Seeding
- **Execution Boundary & Fallback:**
  - Runs **asynchronously** inside `_step_code_index` when `evidence_store.recent_paths` is empty, ensuring project registration (`register()`) remains instantaneous and non-blocking.
  - Resilient branch diffing logic:
    1. Check uncommitted changes: `git status --porcelain`
    2. Try remote default branch: `git rev-parse --abbrev-ref origin/HEAD`
    3. Try common branches: `main`, `master`
    4. Fall back to `HEAD~1` or uncommitted changes only
    5. Always include detected entrypoints (`main.py`, `index.ts`, `main.go`, `lib.rs`, etc.)
  - Resolves 1-hop dependencies for these seeds and indexes them immediately.

### 4.6. Deterministic Cards & GPU Batching
- **Trivial File Detection:**
  - Files $< 1200$ bytes matching patterns like re-export index files (`export * from ...`), pure configuration JSON/YAML, or type stub definitions (`.d.ts`, `interface.go`).
  - Synthesize a deterministic summary card based on exported symbols and comments, saving 30–50% GPU inference time.
- **RAG Batching:**
  - Accumulate pending chunks across files up to `rag_batch_size` (default 32) and invoke `embedding_backend.embed_many(chunks)`.

---

## 5. Verification & Acceptance Criteria

1. **Unit & Component Tests:**
   - Polyglot import resolution tests for Go, Rust, C#, Java, C/C++, Ruby, Python, TS.
   - Single-pass ingest cache correctness (cache hits, hash verification, thread safety).
   - In-degree centrality ordering matches expected import hierarchy.
   - Deterministic card synthesizer covers barrel exports without LLM calls.
2. **Cross-Worktree CAS Verification:**
   - Test adding a second worktree with shared files: verify 0 embedding calls and instant completion of RAG and FTS phases.
3. **Regression Suite:**
   - All existing tests in `tests/test_preprocessing_*.py`, `tests/test_code_index_*.py`, and `tests/test_deterministic_*.py` pass without failures.
4. **Tool Quality:**
   - `python tools/release_check.py` passes cleanly.
   - `python -m compileall -q src tools tests` reports no syntax errors.
