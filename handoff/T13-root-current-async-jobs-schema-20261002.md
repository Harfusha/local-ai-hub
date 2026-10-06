# T13 async_jobs root-current handoff — 2026-10-02

**Superseded:** T20 identified the repository rule in `AGENTS.md:87` forbidding migration shims. Do not integrate this earlier versioned-ALTER patch. The no-migration, fail-closed alternative is `T13-root-current-async-jobs-fail-closed-20261002.patch` with receipt `T13-root-current-async-jobs-fail-closed-20261002.md`.

## Root preimage

- Root: `C:\Users\Adam\.local-ai-hub`
- HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`
- `src/local_ai_hub/async_jobs.py`: SHA-256 `AD6F8B6912E7CB836383811DB2AD29C89DA877AFEBC4B8B52C7FD57B8DE0F904`
- `tests/test_async_jobs.py`: SHA-256 `15B9D64B92C6FC71A0E6C50A1ECF9A83B88F0BA059197AFB8B525E587C70384A`
- Root source and test were already dirty before this work; root was not written.

## Patch

- `T13-root-current-async-jobs-schema-20261002.patch`
- SHA-256 `D886500DC4671712D3C26970FBC65A829EE02E1043905C5A57D74305AD801FDC`
- Only two files: `src/local_ai_hub/async_jobs.py` and `tests/test_async_jobs.py`.
- Source hunk replaces the silent drop with explicit `user_version=1` initialization and transactional known-v0 migration. Unknown versions/layouts fail closed; rollback preserves data.
- Test hunk replaces the previous-schema rejection expectation with T13's versioned migration/data-preservation acceptance test. Existing unsupported-layout preservation test remains in place.

## Planned postimage

- `src/local_ai_hub/async_jobs.py`: SHA-256 `733A983A974BBC9698FC9CD3B82BCA000A2704025CD75DE0D341C497ECB6C945`
- `tests/test_async_jobs.py`: SHA-256 `7283E9F0F6AFAF6CC141F4B1C39B16420D73E2EC006FF88ADB2B693B6E3F7068`
- These hashes were produced by applying the patch to the isolated root-current scratch copy.

## Apply and selector receipts

- `git apply --check` against current root preimage: **PASS**; read-only.
- `git apply --check` in the isolated scratch preimage: **PASS**. Applying the patch there produced both planned postimage hashes.
- Root-current selectors (not run; T02 owns the CPU benchmark slot and the user asked to wait for T20 release):
  - `tests/test_async_jobs.py::test_async_jobs_rejects_non_current_schema_without_deleting_rows` — **PENDING SLOT RELEASE**
  - `tests/test_async_jobs.py::test_async_jobs_migrates_previous_schema_without_dropping_rows` — **PENDING SLOT RELEASE**
- Separate candidate receipt remains valid: `T13-async-jobs-schema-safety-20261002.md` records its own two selectors as **2 passed in 0.31s**. That is not root-current validation.
