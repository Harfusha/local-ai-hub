# T10 Windows Tree-sitter crash repair — 2026-10-03

Worktree: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub`  
HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`  
Root checkout not edited; original root test file was read and executed only. No commit.

## Cause and fix

`parse_treesitter` serialized `parser.parse()` but released `_PARSER_LOCK` before walking the returned native tree. `CodeIndex.update_files_batch` uses worker threads for batches over four files, so a worker could reuse the shared parser while another worker traversed its native `Node` objects. The fix keeps parse and language-specific AST extraction inside one critical section. This is a conservative lock scope across supported Tree-sitter languages.

Added `tests/test_t10_treesitter_parser_thread_safety.py` with (1) a deterministic overlap regression proving two native tree walks cannot overlap when one parser is reused, and (2) an eight-file `CodeIndex.update_files_batch` regression covering its threaded parser path.

## Results

- RED proof, prior lock scope restored temporarily: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_treesitter_parser_thread_safety.py::test_parser_lock_covers_native_tree_walk_when_parser_is_reused` — **1 failed in 0.23s**, observed `max_active_walks == 2` instead of `1`.
- GREEN, fixed source: `$env:PYTHONPATH=(Join-Path (Get-Location).Path 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_treesitter_parser_thread_safety.py` — **2 passed in 0.76s**, exit 0.
- Original crash selector was launched once after the fix with candidate source first on `PYTHONPATH`:

```powershell
$candidateSrc=(Resolve-Path 'src').Path; $root='C:\Users\Adam\.local-ai-hub'; $env:PYTHONPATH="$candidateSrc;$(Join-Path $root 'src');$(Join-Path $root 'tests')"; python -B -m pytest -q -p no:cacheprovider --tb=short (Join-Path $root 'tests/test_agent_crash_recovery.py::test_committed_swarm_dispatch_phases_recover_lease_after_restart')
```

That run emitted partial `..` after 10 seconds and returned a still-running session, without final exit/count. The bounded run was terminated per request; process audit found and stopped two matching test processes (the earlier broker reproduction and the one post-fix run). Follow-up process audit: `matching_crash_selector_processes=0`. Treat original selector result as **incomplete; no pass receipt**. It was not repeated.

## Files and hashes

- `src/local_ai_hub/treesitter_parser.py` — SHA-256 `9216B0DADBAA37CC277E53ECD01A8DFCA5E04D41C01CC8D60B7374B8407E2A2A`
- `tests/test_t10_treesitter_parser_thread_safety.py` — SHA-256 `5586C33A19474766418AA725946D752C0E3311DC78244A1EBF7D018271CA7DCF`
- Candidate patch [`t10-windows-treesitter-crash-20261003.patch`](C:/Users/Adam/.codex/worktrees/t10-path-hints/.local-ai-hub/artifacts/handoff/t10-windows-treesitter-crash-20261003.patch) — SHA-256 `FE444CE2EDD2DACBBA0379170E66A4B81C81E60E0796BF140909E9D756718245`

Patch is candidate-worktree-only. Root apply/check was not performed. Remaining acceptance: obtain a complete exact-selector receipt in an authorized run after reviewing current pins; no benchmark or unrelated tests were run.

## Focused schema/callgraph/impact follow-up

On 2026-10-03, the focused candidate selector below passed through `local_ai_command`: **26 passed in 11.53s**, exit 0, execution `1ee122364e8e45f291a5855f2daa29fb`, repository revision `e0c59fad1d7171c6adfe29c5107d43169c8b88b2a84ab68492a62d5aabdb7bf5`.

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location).Path 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_code_index_schema_rebuild.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_ast_impact_acceptance.py tests/test_t10_treesitter_parser_thread_safety.py
```

This covers T10 stale-schema recovery, fallback callgraph parity, AST/index rename-delete and impact cases, plus the new parser-lock/threaded-index regressions. It does not replace the incomplete original crash selector receipt above. No changes to the Windows/Python 3.13 fallback guard, root checkout, or `/api/context/pack`.
