# T10 root-current acceptance handoff r2

Candidate: `C:\Users\Adam\.codex\worktrees\t10-path-hints\.local-ai-hub` at `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
Root: `C:\Users\Adam\.local-ai-hub` at `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Patches **not integrated**; root bytes remain pinned and unchanged by this task.

## Root preimages

- `src/local_ai_hub/code_index.py` — SHA-256 `6eb54f264f156e1dcd7d4b8e1dab3eeb15227273a05a83b5b62cb3e8f43b7598`
- `src/local_ai_hub/repo_tools.py` — SHA-256 `afb79eae567b603db4aecdf07d077a56dd8f1cb7e3562fadb1893176ef8f1e8a`
- `src/local_ai_hub/preprocess.py` — SHA-256 `14cdd83395263470de8468a907045c083c9da54127490ced4b81c5696716ad69`
- `src/local_ai_hub/defaults.toml` — SHA-256 `d688f8546f616b872b2111c1f137c06964035e75c6da8b2a2dd2f420400a039e`
- `tests/test_t10_ast_impact_acceptance.py` — SHA-256 `ce60751c41a5d2469cf364eba6a8a464b3e7385d9bb09401ae8079b0163aeb34` (existing untracked file; patch updates it).
- `tests/test_t10_python_fallback_budget.py` — absent before patch.

## Patch groups

### `t10-root-current-r2-code-index.patch` — code_index

SHA-256: `5aced091921a0a16db35c272ce47313c0db49b49b47b358d32ee490944a54fec`

Changed paths and preimages:

- `src/local_ai_hub/code_index.py` — `6eb54f264f156e1dcd7d4b8e1dab3eeb15227273a05a83b5b62cb3e8f43b7598`

### `t10-root-current-r2-freshness.patch` — freshness

SHA-256: `4d21202161db6b2062a97b4a0bee5041d3dfb3975ae4f1d8346804176bd6af6a`

Changed paths and preimages:

- `src/local_ai_hub/repo_tools.py` — `afb79eae567b603db4aecdf07d077a56dd8f1cb7e3562fadb1893176ef8f1e8a`
- `src/local_ai_hub/preprocess.py` — `14cdd83395263470de8468a907045c083c9da54127490ced4b81c5696716ad69`

### `t10-root-current-r2-python-fallback.patch` — python_fallback

SHA-256: `d37bc3b6bf71d41a3a82c8daa8306b6b45b0d6261937fb47fb1c5dd15846aa39`

Changed paths and preimages:

- `src/local_ai_hub/repo_tools.py` — `afb79eae567b603db4aecdf07d077a56dd8f1cb7e3562fadb1893176ef8f1e8a`
- `src/local_ai_hub/defaults.toml` — `d688f8546f616b872b2111c1f137c06964035e75c6da8b2a2dd2f420400a039e`

### `t10-root-current-r2-tests.patch` — tests

SHA-256: `7dd2e8e6be52841f4ce336c31f109cce54a6656a66ef301db50fedb1989d7ded`

Changed paths and preimages:

- `tests/test_t10_ast_impact_acceptance.py` — `ce60751c41a5d2469cf364eba6a8a464b3e7385d9bb09401ae8079b0163aeb34`
- `tests/test_t10_python_fallback_budget.py` — `ABSENT`

Scope: CodeIndex forced snapshot refresh/query-cache invalidation; authoritative preprocess hash invalidation; independent `python_fallback_max_files` count cap/default and output metrics, with ripgrep separately time-bounded; T10 AST/fallback tests. Excludes path-hint consumers in `services.py` and `tool_agent.py`.

## Apply and overlay receipts

From the pinned root, ran `git apply --check <patch>` independently for each patch. All four passed. The tests patch is root-current: it updates the already present untracked AST acceptance file and adds the absent fallback-budget test.

Copied root `src/local_ai_hub` and `tests` into temporary overlay `C:\Users\Adam\AppData\Local\Temp\t10-root-current-r2-frzfjevl`, applied all four patches sequentially, then ran exactly:

```powershell
python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py tests/test_t10_python_fallback_budget.py
```

Result: **12 passed in 1.26s** (exit 0). No root files written.

No further benchmark was run for this handoff. T10 broader latency/coverage matrix and additional dead-code/affected-test/API-spec/invariant fixtures remain open; this handoff does not claim T10 completion.

## Final shared-root drift recheck

After the pinned checks and overlay run, the final check found T20/shared-root edits at the same HEAD. Current root source hashes are now:

- `src/local_ai_hub/code_index.py`: `ff5c2f010c9c02ac5916c99c6e6859f2e90f5457dba103dce5e9a83816bac3e9`
- `src/local_ai_hub/repo_tools.py`: `360734ceb316a8a9fc698c19c1098d88fc591170dbbf5f3b67db6608cd3a6a36`
- `src/local_ai_hub/preprocess.py`: `86715359388ca1598dde14c01ffcb4a23590263f99e13554d48502b50d4e961f`
- `src/local_ai_hub/defaults.toml`: `418b62992343d074c33bb6df7d2e8139f2b0ddcd6b47cdb1a4e94971a502d57b`
- `tests/test_t10_ast_impact_acceptance.py`: `b300fb05514ec5daf7078aaddfe84235d20ec059104df8323b4dae6a8049219d`
- `tests/test_t10_python_fallback_budget.py`: `d2d810213f0230af20b42152e0e7c19d03f42896eb692e5a7c4af7127d117b20`

The CodeIndex patch recheck now fails at `src/local_ai_hub/code_index.py:572`; therefore r2 is a historical root-current handoff for the earlier pins and **must not be applied to the current root as-is**. Root changed outside this task; no root writes were made here. Original overlay receipt above remains valid for its recorded source preimages.

## Superseded by T20 root integration

T20 reports all four r2 deltas integrated at root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`, with the AST/fallback suites passing **12/12 in 1.36s**. This result is T20-reported and was not rerun here. R2 patches are archival; do not apply them again. No root writes or tests were run in this final status update.

Current root SHA-256:

- `src/local_ai_hub/code_index.py`: `ff5c2f010c9c02ac5916c99c6e6859f2e90f5457dba103dce5e9a83816bac3e9`
- `src/local_ai_hub/repo_tools.py`: `360734ceb316a8a9fc698c19c1098d88fc591170dbbf5f3b67db6608cd3a6a36`
- `src/local_ai_hub/preprocess.py`: `86715359388ca1598dde14c01ffcb4a23590263f99e13554d48502b50d4e961f`
- `src/local_ai_hub/defaults.toml`: `418b62992343d074c33bb6df7d2e8139f2b0ddcd6b47cdb1a4e94971a502d57b`
- `tests/test_t10_ast_impact_acceptance.py`: `b300fb05514ec5daf7078aaddfe84235d20ec059104df8323b4dae6a8049219d`
- `tests/test_t10_python_fallback_budget.py`: `d2d810213f0230af20b42152e0e7c19d03f42896eb692e5a7c4af7127d117b20`
