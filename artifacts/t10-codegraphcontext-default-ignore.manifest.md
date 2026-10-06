# T10 generated-metadata inventory patch

## Finding

T21's `default_ignore_dirs` contains `.serena` and `.local-ai-hub` but omits `.codegraphcontext`. Its existing Git inventory path can therefore return `.codegraphcontext/generated.py`; T10 candidate includes all three defaults. The retained regression asserts none of the three metadata directories enter `RepositoryTools.iter_files`.

## Narrow patch

Patch changes one default-ignore line in `src/local_ai_hub/repo_tools.py`: add `.codegraphcontext`. It does not touch T21 `search_paths`, any service, or `/api/context/pack`.

Patch SHA-256: `45F7CDAE2E0F712A5A27A95AB1E232E37BBCE0713223BDF701CEF4F3765E5DAF`.

## Candidate identity

- T10 candidate HEAD: `7a36be3b8b69531dccd9215515ac793369da0a44`
- `repo_tools.py` HEAD blob: `35b6ec45b40abeb6c18c32368454727d537b9923`
- `repo_tools.py` working-tree blob: `bba1175e99630554614bd49c01c71417202c1fe4` (contains parallel/pre-existing hunks; packaged patch isolates the default-ignore line)
- `tests/test_repo_tools.py` HEAD and working-tree blob: `fc0d5aad6c4c46c19bcbb7cb7cb28ba5befefe0a`; regression already present, no test file change needed.

## T21 target precondition and read-only check

- T21 target HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- T21 `repo_tools.py` HEAD blob: `bde9d8e8a31f2237ce75ec1f3b7096b0ee219de9`
- T21 current worktree blob: `3ad2adbe74fb15a92fe4aea95fed851424c665b3` (parallel T21 changes retained)
- `git apply --check 'C:/Users/Adam/.codex/worktrees/t10-resume-20260926/.local-ai-hub/artifacts/t10-codegraphcontext-default-ignore.patch'` succeeded against that T21 worktree. No T21 files changed.

## Focused T10 receipt

Command:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_repo_tools.py::test_generated_tool_metadata_never_enters_inventory
```

Receipt: `1 passed in 2.00s`.

## Downstream T21 integration receipt

T21 owner reports that the one-line hunk was applied in the existing T21 worktree after matching worktree blob `3ad2adbe74fb15a92fe4aea95fed851424c665b3` and passing `git apply --check`. T21 reports `.codegraphcontext` added at `repo_tools.py:94`; its parallel `search_paths` hunk was preserved.

Reported focused suite:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_project_config_service_integration.py tests/test_repo_tools.py tests/test_repo_cache_outcomes.py
```

Owner-reported receipt: `28 passed in 7.99s`. Owner reports `git diff --check` clean apart from CRLF warnings on unrelated T21 paths. This receipt is relayed, not independently rerun by T10.
