# T13 candidate async_jobs no-migration checkpoint — 2026-10-02

## Candidate state

- Candidate: `C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub`
- HEAD: `6050c41ce5510a6de3eaeb674a180560ea404f24`
- Owned files: `src/local_ai_hub/async_jobs.py`, `tests/test_async_jobs.py`.
- Source SHA-256: `F564E9047A8F6FE6417D803727C77F5B98E7E9DD090EA99B58DB787DF57F92C8`
- Test SHA-256: `B65D108A9A72C42D951B4961895AC497D1E40BDCA8D5A77A1C6E64914163912E`

## Scoped delta

- `handoff/T13-candidate-async-jobs-no-migration-20261002.patch`
- SHA-256 `A81A435B2EB934E0BF34B942E9D70FFB471DA4DAEB421D03C6210A1575B10557`
- Replaces this candidate's versioned `ALTER TABLE` migration with fail-closed schema validation; no `ALTER TABLE`, `DROP TABLE`, or `user_version` remains in `async_jobs.py`.
- Changes only the T13 previous-schema test to require `RuntimeError` while preserving the legacy table columns, job row, and version 0. Other inherited dirty files remain untouched.
- `git apply --reverse --check` against the candidate postimage: **PASS**.
- Read-only root/candidate `_init_db` schema-block comparison: **identical**, 30 normalized lines; SHA-256 `A9DCB9B354F99D821009A28DB5FDC741572E73597122DB5CB4FC745FC62558D9` in both.
- Syntax-only review, no test execution: `python -B -c "import ast,pathlib; ps=[pathlib.Path(r'C:\Users\Adam\.local-ai-hub\src\local_ai_hub\async_jobs.py'),pathlib.Path(r'C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub\src\local_ai_hub\async_jobs.py'),pathlib.Path(r'C:\Users\Adam\.codex\worktrees\t13-operational-mode\.local-ai-hub\tests\test_async_jobs.py')]; [(ast.parse(p.read_text(encoding='utf-8')),print('AST_PARSE=PASS',p)) for p in ps]"` — **3 files parsed**.

## Validation and blockers

- Exact candidate selectors, **not run** while T02 holds the exclusive test/benchmark slot:
  - `tests/test_async_jobs.py::test_async_jobs_rejects_unknown_schema_without_modifying_database` — **PENDING**.
  - `tests/test_async_jobs.py::test_async_jobs_rejects_previous_schema_without_mutating_rows` — **PENDING**.
- Prepared command, **not executed**:

```text
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_async_jobs.py::test_async_jobs_rejects_unknown_schema_without_modifying_database tests/test_async_jobs.py::test_async_jobs_rejects_previous_schema_without_mutating_rows
```
- The prior candidate receipt `T13-async-jobs-schema-safety-20261002.md` records **2 passed in 0.31s** for the superseded versioned-migration implementation. That result does not verify this no-migration candidate state.
- Root-current no-migration hunk is integrated by T20; current root source SHA-256 `CBB599D76A08BFF38F95A2AFA34DA11FFCFC96C54065D0F313E518B69D9CB950`. T20 reports both root preservation selectors passed.
- End-to-end T13 goal remains blocked on the original acceptance condition: a valid T19 full-suite result for a clean candidate. Do not infer completion from the narrow/root selectors.
- System goal state remains **BLOCKED**. Workspace checkpoint is recorded in `T13-root-current-manifest-20261001.md`; Hub coordination/checkpoint service remains unavailable and was not retried.
