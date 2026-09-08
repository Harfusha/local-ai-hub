# Git-Aware Incremental Repository Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Git repositories hash and preprocess only modified or untracked files, reuse clean tracked content across worktrees, and fail safely to the existing filesystem path.

**Architecture:** Add one bounded Git snapshot per repository/hash generation in `RepositoryTools`. The snapshot tracks worktree/index/tree identity, status categories, and index blob OIDs. `ProjectPreprocessor` seeds clean tracked rows from `git:<blob-oid>`, keeps dirty/untracked paths byte-hashed, and reuses content-derived records only when content and analyzer context match. Git acceleration is read-only; existing timeout and filesystem fallback paths remain authoritative when Git is unavailable or ambiguous.

**Tech Stack:** Python 3.11+, Git CLI, SQLite, pytest, existing `RepositoryTools`, `ProjectPreprocessor`, `RepoState`, `CodeIndex`, `DeterministicEngine`, `RAGStore`, and metadata-only runtime statistics.

---

## Task 1: Add failing Git snapshot tests

**Files:**
- Create: `tests/test_git_incremental_cache.py`
- Inspect: `src/local_ai_hub/repo_tools.py`

- [ ] **Step 1: Write tests for Git status classification and blob identity**

Create a temporary repository with tracked, staged, modified, deleted, renamed, untracked, symlink, and submodule-like entries where the platform supports them. Assert the snapshot classifies each path without reading file contents and returns `git:<oid>` only for clean tracked index entries.

```python
def test_git_snapshot_separates_clean_dirty_and_untracked_paths(tmp_path):
    repo = make_git_repo(tmp_path)
    write_and_commit(repo, "clean.py", "clean = 1\n")
    write_and_commit(repo, "rename.py", "rename = 1\n")
    write_file(repo / "dirty.py", "dirty = 1\n")
    run_git(repo, "add", "dirty.py")
    write_file(repo / "dirty.py", "dirty = 2\n")
    write_file(repo / "untracked.py", "untracked = 1\n")
    run_git(repo, "mv", "rename.py", "renamed.py")
    run_git(repo, "rm", "clean.py")

    snapshot = RepositoryTools(...).git_snapshot(str(repo))

    assert snapshot.blobs["dirty.py"].state == "staged_and_worktree_modified"
    assert snapshot.blobs["untracked.py"].state == "untracked"
    assert snapshot.deleted == ("clean.py",)
    assert snapshot.renames["renamed.py"] == "rename.py"
    assert snapshot.blobs["clean.py"].oid is None
```

- [ ] **Step 2: Run only the new test and verify the expected RED failure**

Run: `python -m pytest -q tests/test_git_incremental_cache.py`

Expected: FAIL because `git_snapshot` and its status/blob result types do not yet exist.

- [ ] **Step 3: Commit the failing test**

Run: `git add tests/test_git_incremental_cache.py` then `git commit -m "test: define git snapshot classification"`.

## Task 2: Implement bounded Git snapshot and blob-map reuse

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py`
- Test: `tests/test_git_incremental_cache.py`

- [ ] **Step 1: Add typed snapshot records and stable identity fields**

Add immutable internal records for repository identity, per-path Git state, and the snapshot. Include `common_dir`, `worktree_root`, `git_dir`, `index_path`, `index_signature`, `head_oid`, `tree_oid`, `status`, `blobs`, `deleted`, and `renames`. Keep raw SHA-256 out of clean tracked records; represent clean content as `git:<blob_oid>`.

- [ ] **Step 2: Add one bounded Git snapshot command path**

Use `git -C <root> rev-parse --git-common-dir --git-dir --git-path index HEAD`, `git ls-files --stage -z`, and `git status --porcelain=v2 -z`. Parse NUL-delimited output strictly. Cache only while root, worktree, index signature, and status identity remain unchanged. Reuse the existing Git timeout, cooldown, and hidden subprocess helpers.

- [ ] **Step 3: Preserve the existing compatibility API**

Implement `RepositoryTools.git_blob_map(root)` as the complete clean-tracked map. Keep `git_blob_hashes(root, paths)` as a filtering wrapper. On timeout, malformed output, missing Git, or non-zero exit return the existing empty/degraded signal; callers must not treat it as proof that no files are tracked.

- [ ] **Step 4: Run the snapshot tests and verify GREEN**

Run: `python -m pytest -q tests/test_git_incremental_cache.py`

Expected: all snapshot classification, cache reuse, timeout, malformed-output, and worktree identity tests pass.

## Task 3: Make preprocessing hash only dirty and untracked paths

**Files:**
- Modify: `src/local_ai_hub/preprocess.py`
- Modify: `src/local_ai_hub/repo_tools.py`
- Test: `tests/test_git_incremental_cache.py`

- [ ] **Step 1: Write the failing clean-path seeding test**

Create a temporary Git repository with a committed source file. Patch the byte-hash helper to raise if called. Run inventory/hash preprocessing and assert the file row contains `git:<blob_oid>`, `needs_hash=0`, and the byte-hash helper was not called.

```python
def test_clean_tracked_file_seeds_git_hash_without_byte_read(tmp_path, monkeypatch):
    repo = make_git_repo(tmp_path)
    write_and_commit(repo, "module.py", "value = 1\n")
    preprocessor = make_preprocessor()

    monkeypatch.setattr(preprocessor, "_hash_file_only", lambda *_: (_ for _ in ()).throw(AssertionError("byte read")))
    preprocessor._step_inventory(str(repo), force=True)
    preprocessor._step_hash(str(repo), budget_seconds=2.0)

    row = read_file_ref(preprocessor, str(repo), "module.py")
    assert row["hash"].startswith("git:")
    assert row["needs_hash"] == 0
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest -q tests/test_git_incremental_cache.py::test_clean_tracked_file_seeds_git_hash_without_byte_read`

Expected: FAIL because inventory currently leaves the file pending for byte hashing.

- [ ] **Step 3: Implement clean seeding and one-map-per-hash-run lifecycle**

Load one Git blob map after inventory metadata is available. Seed only clean tracked paths. Keep staged/worktree-modified and untracked paths pending. Store the map under the existing root/generation hash-run cache, invalidate it when phase, generation, index signature, or status identity changes, and prevent later hash batches from launching duplicate Git probes.

- [ ] **Step 4: Add dirty/untracked/deleted/renamed assertions**

Assert dirty and untracked files still invoke byte hashing, deleted files remove path-local rows, and renamed clean content can reuse the source content identity without sharing path-scoped rows.

- [ ] **Step 5: Run focused preprocessing tests and verify GREEN**

Run: `python -m pytest -q tests/test_git_incremental_cache.py tests/test_v1_2_performance.py tests/test_preprocessor_and_deterministic.py`

Expected: all selected tests pass without duplicate Git map calls.

## Task 4: Make worktree and content-derived reuse safe

**Files:**
- Modify: `src/local_ai_hub/repo_state.py`
- Modify: `src/local_ai_hub/preprocess.py`
- Modify: `src/local_ai_hub/code_index.py` only if existing content lookup requires the new identity
- Test: `tests/test_git_incremental_cache.py`

- [ ] **Step 1: Write worktree identity tests**

Create two linked worktrees at the same commit. Assert clean content-derived records are reusable, but each worktree keeps independent path rows. Modify the second worktree index/worktree and assert its state no longer reuses the clean snapshot from the first.

- [ ] **Step 2: Add worktree/index/tree identity to repository fingerprints**

Include common Git directory, worktree-specific Git directory, index signature, HEAD/tree identity, and relevant status identity in repository-state keys. Do not key path-local rows only by commit because two worktrees can have different uncommitted contents.

- [ ] **Step 3: Preserve content reuse boundaries**

Reuse parse/fact/source/lexical/CodeIndex data by content identity plus relative path and analyzer/config version. Keep RAG path rows and project-specific import context local. Invalidate or rehash when config, ignore rules, filters, sparse state, or analyzer version changes.

- [ ] **Step 4: Run worktree tests and verify GREEN**

Run: `python -m pytest -q tests/test_git_incremental_cache.py tests/test_v1_8_phase8.py tests/test_v2_3_work_orchestrator.py`

Expected: cross-worktree reuse passes while worktree-local state remains isolated.

## Task 5: Add conservative Git feature detection and observability

**Files:**
- Modify: `src/local_ai_hub/repo_tools.py`
- Modify: `src/local_ai_hub/preprocess.py`
- Modify: `src/local_ai_hub/defaults.toml` only if a non-mutating feature flag is needed
- Modify: `docs/CONFIGURATION.md` and `docs/DASHBOARD.md`
- Test: `tests/test_git_incremental_cache.py`

- [ ] **Step 1: Write special-mode and fallback tests**

Cover symlink, submodule entry, sparse-checkout, LFS/filter indicators, `assume-unchanged`, `skip-worktree`, missing Git, timeout, malformed output, and non-Git roots. Assert ambiguous paths fall back to byte hashing or invalidation and no Git config is modified.

- [ ] **Step 2: Implement read-only feature detection**

Detect existing `core.fsmonitor`, untracked-cache, sparse-checkout, filter/LFS, submodule, symlink, and skip-worktree state. Never enable or write these settings automatically. Route unsupported or ambiguous states to the existing filesystem fallback.

- [ ] **Step 3: Add metadata-only counters**

Expose counters for Git snapshots, skipped/computed hashes, blob/tree reuse, degraded Git snapshots, and fallback paths through existing repository/preprocessor statistics. Do not include paths, source, prompts, or file content in telemetry.

- [ ] **Step 4: Run fallback tests and verify GREEN**

Run: `python -m pytest -q tests/test_git_incremental_cache.py tests/test_repo_cache_outcomes.py tests/test_preprocessor_and_deterministic.py`

Expected: fallback and special-mode tests pass; no public MCP schema changes.

## Task 6: Integrated verification and review

**Files:**
- Modify: `CHANGELOG.md` only if project convention requires a release note
- Test: existing suite and release checks

- [ ] **Step 1: Run compile validation**

Run: `python -m compileall -q src mcp tools tests`

Expected: exit code 0.

- [ ] **Step 2: Run targeted regression suite**

Run: `python -m pytest -q tests/test_git_incremental_cache.py tests/test_v2_4_token_accounting.py tests/test_v2_release.py tests/test_surface_and_packaging.py`

Expected: zero failures.

- [ ] **Step 3: Run the full suite with an explicit config path**

Run: `python -c "import os,pytest; os.environ['LOCAL_AI_CONFIG']=r'C:\\Users\\Adam\\.local-ai-hub\\config.toml.example'; raise SystemExit(pytest.main(['-q']))"`

Expected: record any pre-existing flaky or environment-specific failure separately; do not mask failures by changing tests.

- [ ] **Step 4: Run indexed impact/review and inspect the diff**

Run `local_ai_repo(action="impact")`, `local_ai_repo(action="review_diff")`, and `git diff --check`. Confirm public MCP schemas remain unchanged and all modified paths are within the approved design.

- [ ] **Step 5: Commit implementation as focused commits**

Use focused Conventional Commits for snapshot/reuse, preprocessing integration, and tests/docs. Do not stage or alter unrelated pre-existing worktree changes.
