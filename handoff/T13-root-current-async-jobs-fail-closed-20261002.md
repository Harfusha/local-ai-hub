# T13 async_jobs root-current fail-closed handoff — 2026-10-02

## Root preimage

- Root: `C:\Users\Adam\.local-ai-hub`
- HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`
- `src/local_ai_hub/async_jobs.py`: SHA-256 `AD6F8B6912E7CB836383811DB2AD29C89DA877AFEBC4B8B52C7FD57B8DE0F904`
- `tests/test_async_jobs.py`: SHA-256 `15B9D64B92C6FC71A0E6C50A1ECF9A83B88F0BA059197AFB8B525E587C70384A`
- Both root files were already dirty. Root was not written.

## Patch

- `T13-root-current-async-jobs-fail-closed-20261002.patch`
- SHA-256 `7F4142A928E411633A76169156BD5AE22345B6E7240EE740B84F922D5BC5E2F0`
- Only changes `src/local_ai_hub/async_jobs.py`; no broader async-job diff or test-file changes.
- Removes both `ALTER TABLE` and `DROP TABLE` behavior. An existing table with unsupported columns raises `RuntimeError` inside a transaction and leaves table/data intact. A missing table is created at the current schema. No migration shim/version upgrade is added, following `AGENTS.md:87`.
- Root's current test preimage already contains tests for preserving rows on non-current and legacy layouts, so this patch preserves those tests unchanged.

## Planned postimage

- `src/local_ai_hub/async_jobs.py`: SHA-256 `CBB599D76A08BFF38F95A2AFA34DA11FFCFC96C54065D0F313E518B69D9CB950`
- `tests/test_async_jobs.py`: unchanged, SHA-256 `15B9D64B92C6FC71A0E6C50A1ECF9A83B88F0BA059197AFB8B525E587C70384A`
- Applying the patch to an isolated copy of the root preimage produced both planned hashes.

## Apply and selector receipts

- Read-only `git apply --check` against current root preimage: **PASS**.
- `git apply --check` against isolated scratch preimage: **PASS**; scratch apply postimages match the hashes above.
- Exact root-current selectors:
  - `tests/test_async_jobs.py::test_async_jobs_rejects_non_current_schema_without_deleting_rows` — **PASS** (T20 root-current run).
  - `tests/test_async_jobs.py::test_async_jobs_rejects_legacy_schema_without_mutating_rows` — **PASS** (same serial T20 root-current run).
- Same serial root batch: `test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources` — **PASS**.
- Unrelated release-contract selector — **FAIL**, pre-existing `ALTER TABLE` marker in T10-owned `src/local_ai_hub/code_index.py`; outside T13 scope, no T13 edit.
- Separate candidate-only result remains in `T13-async-jobs-schema-safety-20261002.md` (**2 passed in 0.31s**); it is not evidence for this root-current patch.
- T20 status: reported the fail-closed patch applied after preimage/apply-check and scope/postimage verified. No further T13 root edits requested.
