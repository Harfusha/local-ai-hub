# T10 root-current consumer patch

Date: 2026-10-01 (Europe/Prague)

This is the concrete T10 consumer patch package for T20 review. Canonical source and regression code live in the T10 candidate worktree; root checkout remains untouched. Patch only listed consumer hunks into root-current files. Do not replace whole T13/T20 methods.

## Pinned roots

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Candidate: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub`, HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`.
- Root live SHA-256: `preprocess.py` `14cdd83395263470de8468a907045c083c9da54127490ced4b81c5696716ad69`; `code_index.py` `6391647e32a21e0a20a0caa253f80eb62fe6e009158272cb08090fb1cc12a3a4`; `treesitter_parser.py` `23c5f647ec3ba3fd545b7f8e8b5ae59b781f317287b1b539fe8e0a06345cc57f`; `project_config.py` `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`; `services.py` `1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1`.
- Candidate source pins are in `artifacts/t10-root-current-config-overlay-acceptance-20261001.md`; no root file changed during this work.

## Source patch scope

### `preprocess.py`

Copy candidate helpers `_project_config_context`, `_project_profile`, `_project_path_allowed`, and `_add_project_text_extensions` after root `_consume_dirty_paths`. They lazily resolve the root `project_config` API, preserve missing-module behavior, enforce preprocess path/size rules, and add configured text extensions while subtracting binary and built-in extensions.

In root `cache_fingerprint`, include `project_context.config_digest` in fingerprint identity and returned metadata. In `_step_inventory`, filter each candidate by `path_is_allowed(..., phase="preprocess", size_bytes=...)`; include config digest and project type, solution path, and language overrides in structural identity. Keep existing seeded-content, invalidation, and generation logic.

For watcher consumers, apply these exact candidate checks in `_watch_relevant` and `_step_incremental_inventory`:

```python
project_extensions: set[str] = set()
_api, project_context = self._project_config_context(str(root))
if project_context is not None:
    settings = project_context.settings
    project_extensions.update(str(value).lower() for value in getattr(settings, "text_extensions", ()))
    for override in getattr(settings, "language_overrides", {}).values():
        project_extensions.update(str(value).lower() for value in override.get("text_extensions", ()))
    project_extensions.difference_update(str(value).lower() for value in getattr(settings, "binary_extensions", ()))
if any(Path(rel).name in {".local-ai.toml", ".local-ai.worktree.toml"} for rel in paths):
    return False  # full inventory; config can change policy for paths outside dirty batch
```

The T10 candidate also checks incremental dirty paths with `path_is_allowed`; newly excluded stale refs enter existing deletion bookkeeping. `_step_code_index` carries file size into policy, filters denied refs before pruning/reindex, and uses the existing batch update.

At root `_step`, preserve the T13 `_background_work_allowed()` gate, pause/cancel checkpoints, yields, and status writes. Splice only T10 phase skips after phase load: `call_graph` skip prunes CodeIndex then advances to `deterministic`; `modules` skip advances to `project`. In diagnostics, wrap only profile lookup with `_project_profile(root, ...)`; keep timeout, diagnostic-baseline SQL, and completion unchanged.

### `code_index.py` and `treesitter_parser.py`

Insert candidate `_project_config_context` and `_language_for_path` after root `CodeIndex._lang`; fallback must call the root `CodeIndex._lang(path)`. Apply phase/path/size guards to `files_needing_reindex`, `update_file`, and `update_files_batch`. Compare stored content hash, analyzer version, and configured language so override changes reindex. Remove denied stale rows with root-owned SQL/cache invalidation. Do not transplant candidate whole `update_files_batch` or `_remove_indexed_paths`: they also replace root parser-result hydration, transaction, and cache behavior.

Insert candidate `language_for_path(path, fallback_language, settings)` after root `is_treesitter_available`. It maps configured extensions to override languages, then returns the unchanged fallback. Keep root parser dispatch and language capability map intact.

## Regression patch

Candidate `tests/test_t10_project_config_consumers.py` now asserts:

- actual root `project_config.py` and `services.py` import origins and SHA-256;
- allowed lexical hint is targeted; excluded hint is denied; stale repository revision and config digest hints are not targeted;
- seeded parent refs are filtered; configured `.pyx` is indexed as Python and watcher-relevant;
- incremental inventory removes a newly excluded stale row and falls back to full inventory for config-file changes;
- cache fingerprint changes after config digest changes without advancing phase/generation;
- parent Gemini diagnostic seed and linked diagnostic seed survive inventory; diagnostics then update only linked baseline.

The candidate AST caller selector remains `tests/test_t10_retrieval_edges.py::test_deterministic_callers_intent_combines_direct_symbols_path_hints_and_ast_edges`. This validates direct symbols plus indexed AST callers; root integration still needs T20's root-side counterpart.

## Evidence and limits

- Consumer overlay: **5 passed**; root `project_config.py` and `services.py` loaded by absolute path and asserted by hash. Receipt includes allowed/excluded/stale hints, custom watcher extension, incremental exclusion cleanup, parent/linked Gemini seed preservation, cache invalidation, and diagnostics.
- Supported Tree-sitter call edges: **9 passed, 2 deselected** across Python, C#, TypeScript, TSX, JavaScript, Go, and Rust.
- Java and C++: parser unavailable; their fixtures remain and skip on capability check. Bounded selector returned **1 passed, 2 skipped, 8 deselected**. CodeIndex generic fallback is not counted as a Tree-sitter pass.
- Root current `CodeIndex`/`ProjectPreprocessor` consumers are not loaded by the overlay; candidate consumer code is tested against actual root config and services. Root integration and its verification remain T20-owned.
- Preserve Gemini seed and diagnostics. Do not edit root. Do not run 100k benchmark until T20 grants exclusive CPU slot.

Latest candidate pins: package source tree `cbe75a7e54743b49de7ffee932aaeeff0b939613014dbffdf57f64245fb682b6`; candidate-scoped patch `9cc116c4a761374b98cae61577d3b41b6f9c8d194b4acd1b509ef1d445edc3fc`; consumer-source patch `8e22bf549192e6164a13803e5917e4fb9c40403bb206288095462f451adb42f9`. Latest combined bounded suite: **21 passed, 2 skipped in 7.53s**; config event reaches full inventory, receipt confirms `config_change_full_inventory_used=true`.
