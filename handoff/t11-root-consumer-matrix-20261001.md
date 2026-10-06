# T11 root consumer matrix receipt

## Scope and ownership

- Root reviewed read-only: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Requested T11 candidate: `C:\Users\Adam\.codex\worktrees\t11-rag-recovery-v2\.local-ai-hub`, HEAD `8c945bdeb5f92270613e53b307b6f646a4f0e21b`.
- Candidate source predates project-config integration: it has no `src/local_ai_hub/project_config.py`; `RAGStore._iter_files(root)` accepts no project context. Candidate has only the older three RAG test files. It cannot produce consumer-matrix evidence for current root behavior.
- Root is T20-owned. No root files changed; no root tests or benchmarks ran. Overlay used fake embeddings, temporary SQLite state, and local Git only. No GPU, Hub, or port was used.
- Candidate overlay test `tests/test_t11_root_consumer_overlay.py` targets current root source with `-o pythonpath=C:/Users/Adam/.local-ai-hub/src`. Candidate `tests/conftest.py` prepends candidate `src`, so invocation uses `--noconftest`; first test asserts `rag.__file__` is root source.
- Overlay receipt: source assertion passed. Eight focused extension, size, worktree phase, and config-digest tests passed. Explicit ignored-path case then failed: `index_paths_step` retained `generated/keep.py` after `rag.ignore_dirs=["generated"]`. This confirms bypass against root source, not an integrated-root receipt.
- Handoff patches passed root `git apply --check`.

## Root source trace

- `RAGStore.project_context` lazily imports project config and calls `resolve_project_context(root, state_dir)` on each RAG entrypoint (`src/local_ai_hub/rag.py:292-306`). Resolver layers apply in order: primary worktree project, current project, Git-common machine config, linked-worktree override (`src/local_ai_hub/project_config.py:806-850`). Later layer values override matching earlier keys.
- Full index resolves context and gates the `rag` phase (`rag.py:760-765`), then enumerates through `_iter_files` (`rag.py:340-405`). Incremental index also gates the phase and delegates selected files to `index_paths_step` (`rag.py:1406-1474`). Explicit-path indexing resolves context and gates phase (`rag.py:1084-1093`).
- `_iter_files` applies `rag.max_file_bytes`, caps it with project `max_file_size_bytes`, admits configured custom text extensions, rejects binary extensions, and calls project path policy (`rag.py:346-399`). `index_paths_step` also handles extension, size, and project path policy (`rag.py:1180-1210`).
- `preprocess.exclude_paths` is phase-specific. Root consumer test checks that RAG still indexes such a path through all three entrypoints (`tests/test_t11_rag_project_policy.py:51-67`). Root test also checks `skip_phases=["rag"]` across all three (`:70-85`).
- Linked-worktree source inheritance has generic resolver coverage (`tests/test_project_config_worktrees.py:23-77`); T11 parent seeding tests verify matching file-cache reuse, dirty-child invalidation, and that `rag_hash` is never inherited (`tests/test_t11_rag_seed_integrity.py:121-183`). The legacy chunks-schema test verifies migration resets stale rows and adds `embedding_space` (`:287-325`).
- Reindex coverage changes the embedder-reported space ID, not embedding configuration itself (`tests/test_t11_embedding_space_reindex.py:34-66`). Separate embedding-cache tests change digest/revision, but do not prove RAG full-index reindex after that config change. Test-only patch below adds this consumer check.
- Generic project-config tests cover force-include precedence, custom binary classification, size policy, and linked-worktree overrides. Root has no RAG consumer test for custom text/binary extensions and project size limits across all three entrypoints. New tests below cover those cases.
- Confirmed overlay gap: `_iter_files` rejects `rag.ignore_dirs`, but explicit `index_paths_step` bypasses it for caller-supplied paths. New overlay test reproduced stale indexed data remaining searchable in the DB.

## Root-current test patches

- `handoff/t11-root-consumer-matrix-tests-red.patch`, SHA-256 `1D2D043647E1380D0552629F7DF4D95FD9F68967EFC7F2204C803B487CD90C36`. Adds file-growth/size/tenant tests, RAG custom-extension and project-size consumer tests, the hard-ignore explicit-path regression, and config-digest-driven full reindex coverage. Tenant test uses `scope="tenant"` and distinct roots; read-bound test matches root API, patches `Path.open`, and measures file size from `stat()`.
- `handoff/t11-root-worktree-rag-phase-test.patch`, SHA-256 `25E8E04F43EF86662218BAF7B3E0DAE539526CC05048C622C9C07B03DB3F8A99`. Adds a local temporary linked-worktree fixture to verify the worktree `skip_phases=["rag"]` override through all three RAG entrypoints. Uses fake embeddings and local Git only.
- `handoff/t11-root-current-rag-ignore-dirs.patch`, SHA-256 `88421F8B79064961C6C72A7100241B95BE17F1E7E53383C6E2056D96B62D3DDA`. Diagnostic guard-only delta prepared after confirmed RED; `git apply --check` passed, root remains unchanged. Do not apply it separately.
- The merged root-current bounded-ingestion and explicit-policy patch is `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-root-current-bounded-ingestion-production.patch`, SHA-256 `565ED6040EAC274512BEE8025E29BCB3278F770B757FFF4589D8A35854E0A85D`. It keeps bounded reads and embedding-space logic, marks ignored/project-policy/binary/extension/size rejections for transactional cleanup, and blocks force-include from bypassing hard ignore. Current root contains this source change; reverse apply-check passes. The post-fix selector remains T20-owned. Do not rerun the 81-test suite or large benchmark.

Overlay commands already run in candidate against current root source:

```powershell
python -B -m pytest -q -x -p no:cacheprovider --noconftest -c pyproject.toml -o pythonpath=C:/Users/Adam/.local-ai-hub/src tests/test_t11_root_consumer_overlay.py::test_000_overlay_imports_actual_root_rag_source
python -B -m pytest -q -x -p no:cacheprovider --noconftest -c pyproject.toml -o pythonpath=C:/Users/Adam/.local-ai-hub/src tests/test_t11_root_consumer_overlay.py -k "not explicit_index_path_cannot_resurrect_rag_ignored_directory"
python -B -m pytest -q -x -p no:cacheprovider --noconftest -c pyproject.toml -o pythonpath=C:/Users/Adam/.local-ai-hub/src tests/test_t11_root_consumer_overlay.py::test_000_overlay_imports_actual_root_rag_source tests/test_t11_root_consumer_overlay.py::test_explicit_index_path_cannot_resurrect_rag_ignored_directory
```

First selected root command after T20 releases the shared slot and applies reviewed patches:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t11_rag_project_policy.py::test_rag_index_paths_respects_hard_ignored_directory_with_force_include tests/test_t11_rag_project_policy.py::test_rag_ingestion_applies_custom_extension_and_project_size_policy tests/test_t11_rag_worktree_policy.py tests/test_rag_read_bounds.py tests/test_t11_embedding_space_reindex.py::test_full_index_reembeds_unchanged_files_when_embedding_space_changes tests/test_t11_embedding_space_reindex.py::test_full_index_reembeds_unchanged_files_after_embedding_config_change tests/test_t11_rag_seed_integrity.py::test_legacy_chunks_schema_without_embedding_space_is_rebuilt tests/test_t11_rag_seed_integrity.py::test_parent_seed_reuses_only_matching_file_cache_and_never_rag_hash tests/test_t11_rag_seed_integrity.py::test_parent_seed_rejects_same_size_dirty_child_and_stale_source_text tests/test_t11_rag_seed_integrity.py::test_parent_seed_invalidates_previously_inherited_state_for_dirty_child
```
