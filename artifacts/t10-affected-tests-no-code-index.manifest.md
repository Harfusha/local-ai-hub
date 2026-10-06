# T10 no-CodeIndex affected-test patch

## Scope

Patch contains only:

- `src/local_ai_hub/deterministic.py`: `DeterministicEngine.affected_tests` lazily builds a `CodeIndex` from the bounded `RepositoryTools.iter_files` inventory when no index is injected, then uses existing transitive `impact` traversal.
- `tests/test_affected_tests_no_code_index.py`: one regression for `src/shared.py -> src/core.py -> src/app.py` and all three tests.

No T15-owned test or T06 path included.

## Candidate identity

- Candidate base HEAD: `7a36be3b8b69531dccd9215515ac793369da0a44`
- Candidate HEAD blob, `deterministic.py`: `ba36b2d9d9b3e4a061f392425f80ad553b716331`
- Candidate working-tree blob, `deterministic.py`: `e777904aad681b5d7f79143c12543707508032a9` (contains other pre-existing dirty hunks; patch exports only the `affected_tests` hunk)
- Candidate regression-test blob: `6f34ae94618daff99adbdd01231600486c21a2d4`
- Patch SHA-256: `2D5BAEB0F8F4C414B18AA275E5E36D46FB1AA542DEFF768CF2FAE0DEA07C80B6`

## Root preconditions

- Root target HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- Root `src/local_ai_hub/deterministic.py` HEAD and worktree blob: `d1fb60a8d68cde08f2983d46aaa6eb5e459336b6`
- Root `tests/test_affected_tests_no_code_index.py`: absent before patch.
- Read-only check from root: `git apply --check 'C:/Users/Adam/.codex/worktrees/t10-resume-20260926/.local-ai-hub/artifacts/t10-affected-tests-no-code-index.patch'` succeeded against the preconditions above. No root files changed.
- Two rejected draft checks had bounded stderr:
  - `error: patch failed: src/local_ai_hub/deterministic.py:4237` / `error: src/local_ai_hub/deterministic.py: patch does not apply`
  - `error: patch failed: src/local_ai_hub/deterministic.py:4236` / `error: src/local_ai_hub/deterministic.py: patch does not apply`
- Cause: draft hunk offsets lacked enough root context. Final patch uses root-context lines and passed the single final check above. No force apply used.

## Focused validation

Command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_affected_tests_no_code_index.py tests/test_t10_transitive_dependencies.py tests/test_affected_tests.py
```

Receipt: `7 passed in 1.57s`.

`git diff --check` reported no whitespace errors. Git emitted existing LF-to-CRLF warnings.
