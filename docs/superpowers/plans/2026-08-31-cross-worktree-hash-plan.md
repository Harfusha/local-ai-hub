# Cross-worktree content identity fast path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a new Git worktree reuse clean tracked content and derived caches without rereading or rehashing the full checkout.

**Architecture:** Load one complete clean-tracked Git blob map per root hash run, seed new worktree file rows directly from those IDs, and keep byte hashing for dirty/untracked paths only. Reuse content-addressed parse/fact/source/RAG data through existing global stores while retaining per-worktree path rows.

**Tech Stack:** Python 3.11+, Git CLI, SQLite, pytest, existing `RepositoryTools`, `ProjectPreprocessor`, `CodeIndex`, `DeterministicEngine`, and `RAGStore`.

**Spec:** `docs/superpowers/specs/2026-08-31-cross-worktree-hash-design.md`

## Global Constraints

- Preserve `git:<blob-id>` and SHA-256 file identity formats.
- Never use directory signatures as canonical content identity.
- Dirty and untracked files must still be byte-read and hashed.
- Public MCP schemas remain unchanged.
- All subprocesses and validation commands stay bounded.

---

### Task 1: One-shot Git blob map

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py:244-287`
- Modify: `src/local_ai_hub/preprocess.py:128,1584-1600`
- Test: `tests/test_deeper_hardening.py`

**Interfaces:**
- Produce `RepositoryTools.git_blob_map(root: str) -> dict[str, str]`, cached per root/index identity for the lifetime of a hash run.
- Keep `git_blob_hashes(root, paths)` as compatibility wrapper filtering the map.
- `ProjectPreprocessor._step_hash` consumes one map per root/generation and never launches duplicate Git probes for later batches.

- [ ] **Step 1: Write the failing test**

Add a test that calls `git_blob_hashes` for two disjoint batches while monkeypatching `subprocess.run`, then asserts the index/diff probe pair is executed once for the stable root cache.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_deeper_hardening.py::test_git_blob_map_is_reused_for_second_batch -q`

Expected: FAIL because the current wrapper reloads Git state after its short TTL.

- [ ] **Step 3: Write minimal implementation**

Extract the existing index/diff parsing into `git_blob_map`, key its cache by root plus Git index metadata and dirty-status identity, and have `git_blob_hashes` filter the returned map. Add a per-root hash-run map in `ProjectPreprocessor` keyed by `(root, generation)` and clear it when hash phase finishes or root is forgotten.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_deeper_hardening.py::test_git_blob_map_is_reused_for_second_batch -q`

Expected: PASS with one Git index/diff probe pair.

- [ ] **Step 5: Run focused regression tests**

Run: `python -m pytest tests/test_hardening.py::test_git_blob_hash_reuses_clean_tracked_content -q`

Expected: PASS.

### Task 2: Seed clean tracked files during inventory

**Files:**
- Modify: `src/local_ai_hub/preprocess.py:1489-1578,1584-1654`
- Test: `tests/test_v1_2_performance.py` or a new focused test in `tests/test_cross_worktree_hash.py`

**Interfaces:**
- Add `_seed_clean_git_hashes(root: str, paths: list[str]) -> dict[str, str]` and `_link_content_reuse(root: str) -> None` helpers.
- Inventory writes clean tracked hashes with `needs_hash=0`; dirty/untracked rows remain `needs_hash=1`.

- [ ] **Step 1: Write the failing test**

Create a temporary Git repo with a tracked file, instantiate `ProjectPreprocessor`, monkeypatch `RepositoryTools._hash_file_only` to raise, run inventory, and assert the tracked row has a `git:` hash and `needs_hash=0`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cross_worktree_hash.py::test_new_clean_worktree_seeds_git_hash_without_byte_read -q`

Expected: FAIL because inventory currently stores an empty hash and marks every new row pending.

- [ ] **Step 3: Write minimal implementation**

Load the one-shot blob map after metadata inventory. In the `file_refs` upsert, use the Git hash for clean tracked paths, set `needs_hash=0`, and preserve old hash/card state only when metadata is unchanged. Keep dirty/untracked paths pending. Invoke `_link_content_reuse` after inventory seeding and after each hash batch so content cards and source rows are linked immediately.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cross_worktree_hash.py::test_new_clean_worktree_seeds_git_hash_without_byte_read -q`

Expected: PASS.

- [ ] **Step 5: Add dirty/untracked guard test**

Assert a modified tracked file and an untracked file still have `needs_hash=1` and invoke `_hash_file_only` during `_step_hash`.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest tests/test_cross_worktree_hash.py tests/test_v1_2_performance.py::test_preprocessor_minor_edit_is_incremental_and_mtime_only_keeps_card -q`

Expected: PASS.

### Task 3: Avoid rereads on content-addressed parser cache hits

**Files:**
- Modify: `src/local_ai_hub/code_index.py:548-640`
- Modify: `src/local_ai_hub/deterministic.py:810-900`
- Test: `tests/test_cross_worktree_hash.py`

**Interfaces:**
- Supplied content hashes may satisfy parser/fact blob lookups before filesystem reads.
- Existing update method signatures and return payloads stay unchanged.

- [ ] **Step 1: Write the failing test**

Populate parse/fact blob stores for a known `git:` hash, monkeypatch `_read_snapshot` to raise, then call each `update_files_batch` with the supplied hash and assert success via cached blobs.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cross_worktree_hash.py::test_code_and_deterministic_reuse_blob_without_read -q`

Expected: FAIL because both methods read the worktree file before querying their blob caches.

- [ ] **Step 3: Write minimal implementation**

For supplied hashes, check existing root rows and parse/fact blobs first. Read bytes only when the supplied hash has no reusable parsed blob. Keep current behavior for calls without supplied hashes and for cache misses.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cross_worktree_hash.py::test_code_and_deterministic_reuse_blob_without_read -q`

Expected: PASS.

### Task 4: Reuse lexical text for RAG path indexing

**Files:**
- Modify: `src/local_ai_hub/rag.py:591-752`
- Modify: `src/local_ai_hub/preprocess.py:1660-1735`
- Test: `tests/test_cross_worktree_hash.py`

**Interfaces:**
- Extend internal `RAGStore.index_paths_step(..., content_overrides: dict[str, str] | None = None)`.
- `_step_rag` supplies source-index text when the same content hash already exists in another worktree; missing overrides use current byte reads.

- [ ] **Step 1: Write the failing test**

Call `index_paths_step` with a content override while monkeypatching `Path.read_bytes` to raise; assert the path is processed and no embedding is needed when global chunks already exist.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cross_worktree_hash.py::test_rag_reuses_source_text_without_read -q`

Expected: FAIL because the current method always reads bytes.

- [ ] **Step 3: Write minimal implementation**

Use override text for chunking and retain current stat/file fallback when absent. Query source-index text by `(root,path,content_hash)` in `_step_rag` and pass only matching rows.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cross_worktree_hash.py::test_rag_reuses_source_text_without_read -q`

Expected: PASS.

### Task 5: Full verification and performance evidence

**Files:**
- Test: `tests/test_cross_worktree_hash.py`
- Check: `docs/superpowers/specs/2026-08-31-cross-worktree-hash-design.md`

- [ ] **Step 1: Run focused suite**

Run: `python -m pytest tests/test_cross_worktree_hash.py tests/test_deeper_hardening.py tests/test_hardening.py -q`

Expected: PASS.

- [ ] **Step 2: Run repository validation through Local AI Hub**

Run: `python -m compileall -q src mcp tools tests` and `python -m pytest -q` via `local_ai_command`.

Expected: PASS with no new failures.

- [ ] **Step 3: Inspect diff and report measured counters**

Compare Git probe count, byte-hash calls, and parser/RAG read calls for a clean new worktree versus a dirty one-file worktree. Report any remaining unavoidable reads.
