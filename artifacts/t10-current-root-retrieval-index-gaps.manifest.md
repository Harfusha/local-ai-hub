# T10 current-root retrieval/index gap patch

Patch: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub\artifacts\t10-current-root-retrieval-index-gaps.patch`  
SHA-256: `17E6481CC223AB93B06A6BFF92F2CB14063942ECAA376DB79166FDB97242079A`  
Target root: `C:\Users\Adam\.local-ai-hub`  
Expected base/current HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`

## Scope

- `src/local_ai_hub/treesitter_parser.py`: index named TypeScript arrow functions as caller scopes.
- `src/local_ai_hub/code_index.py`: separate parser analyzer version from package version; reject stale parse blobs and reindex same-content files when analyzer version changes, including existing SQLite schema migration and single/batch updates.
- `src/local_ai_hub/repo_tools.py`: count capped Python fallback separately from ripgrep timeouts. Timeout counter increments only for `subprocess.TimeoutExpired`.
- `tests/test_t10_retrieval_index_gaps.py`: regression tests for arrow caller indexing, stale parse-blob rejection, single/batch reindex after analyzer-version change, and independent Python fallback/ripgrep timeout counters.

## Patch checks

- Base/index check: `git apply --cached --check --whitespace=error <patch>` — PASS, exit 0. Root index was clean; checked against HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Current-root check: `git apply --check --whitespace=error <patch>` — PASS, exit 0, with existing unstaged root edits present in `code_index.py` and `repo_tools.py`.
- `git apply --stat <patch>` — PASS: src/local_ai_hub/treesitter_parser.py  |   24 +++++++;  src/local_ai_hub/code_index.py         |   39 +++++++----;  src/local_ai_hub/repo_tools.py         |   10 +++;  tests/test_t10_retrieval_index_gaps.py |  112 ++++++++++++++++++++++++++++++++;  4 files changed, 169 insertions(+), 16 deletions(-).
- Patch was not applied. Root files were not written.

## Regression command (not run per request)

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_retrieval_index_gaps.py`
