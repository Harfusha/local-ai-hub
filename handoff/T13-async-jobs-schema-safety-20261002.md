# T13 async_jobs schema safety receipt — 2026-10-02

**Superseded implementation:** this receipt records the earlier versioned-ALTER candidate. Its 2-pass result is historical only; current candidate is no-migration fail-closed. See `T13-candidate-async-jobs-no-migration-20261002.md`.

- Candidate: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`
- Candidate HEAD: `6050c41ce5510a6de3eaeb674a180560ea404f24`
- Source: `src/local_ai_hub/async_jobs.py` SHA-256 `B8674C4A462002FF3625DE7343054932F6A63727FD33C4CFF8F0D4B069829239`
- Tests: `tests/test_async_jobs.py` SHA-256 `34CBEE17460F24149457C5D91F268761F28501BD1AD619430E3008E9CED9E08A`
- Exact delta patch: `handoff/T13-async-jobs-schema-safety-20261002.patch`
- Patch SHA-256: `69DE46855A799DD5AF1DF515C57A5F074700F4112B91D6802B83CA6B4FC1AE04`

## Change

Schema version 1 initialization runs under `BEGIN IMMEDIATE`. Version 0 supports only a fresh database, the exact prior T13 column layout, or the current layout; the known prior layout is upgraded transactionally and versioned. Unsupported versions/layouts raise `RuntimeError`, rollback the transaction, and never drop `async_jobs`. Index creation and `PRAGMA user_version = 1` share the transaction.

## Validation

- RED: `test_async_jobs_rejects_unknown_schema_without_modifying_database` failed before the source edit because no `RuntimeError` was raised.
- GREEN: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_async_jobs.py::test_async_jobs_rejects_unknown_schema_without_modifying_database tests/test_async_jobs.py::test_async_jobs_migrates_previous_schema_without_dropping_rows` — **2 passed in 0.31s**.
- `git apply --reverse --check handoff/T13-async-jobs-schema-safety-20261002.patch` in the candidate — **PASS**; patch exactly describes the post-edit candidate delta.
- Read-only `git apply --check` against root — **FAILS** at `src/local_ai_hub/async_jobs.py:106` and `tests/test_async_jobs.py:295`; root preimage differs. No root files were changed. T20 must adapt/review against its current preimage before integration.
- Local AI Hub was unavailable (`context` and command broker transport failed before write; one status check returned `success=false`), so the two requested selectors ran once via bounded native fallback.
