# T10 preprocessor analyzer-version follow-up

Patch: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub\handoff\t10-preprocessor-analyzer-reindex.patch`  
SHA-256: `D8F142475855E6A4EA8F0FA5EAD581E058113B23B2DF2C04CE36E04753ED6356`  
Root HEAD checked: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`  
Depends on current-root patch already integrated by T20: `t10-retrieval-index-merge.patch` SHA-256 `656297870BF5C8B3C2C29CF7839060E69EA2D92CF30A8276F626BBD380C1F987`.

## Exact paths

- `src/local_ai_hub/code_index.py`: add `files_needing_reindex`, comparing content hash and `_PARSER_ANALYZER_VERSION`.
- `src/local_ai_hub/preprocess.py`: queue unchanged-content refs when analyzer version is stale; retain legacy fallback for older CodeIndex adapters.
- `tests/test_t10_preprocessor_index_version.py`: regression for preprocessing requeue after analyzer bump.

## Read-only proof

- `git apply --check --whitespace=error <patch>` against current root worktree: PASS, exit 0.
- `git apply --stat <patch>`: 3 files, 86 insertions, 4 deletions.
- Patch not applied by T10. Root remains unchanged by this task.

## Validation

- Root test command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_preprocessor_index_version.py` — NOT RUN; T20 shared test slot is allocated elsewhere.
- Existing candidate selector `tests/test_t10_acceptance.py::test_preprocessor_queues_unchanged_files_after_analyzer_version_change` was included in candidate T10 acceptance receipt: 216 passed, 2 skipped in 40.44s. This is candidate evidence, not root proof.
