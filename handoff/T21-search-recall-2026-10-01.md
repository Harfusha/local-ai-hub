# T21 search recall integration receipt — 2026-10-01

Owner: current orchestrator; existing T21 worktree, no replacement task.
Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

## Owned change

Only `handoff/test_t21_root_search_recall.py` and its new-test patch/receipt artifacts.
Patch target: `tests/test_t21_search_recall.py`.
No production files, inherited dirty work, T09/T11 changes or `/api/context/pack` modified.
Root-current search already combines bounded broad and targeted results, filtering project exclusions.
Do not replace it with the older T21 candidate implementation.

## Evidence

1. Existing candidate selector:
   `$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config_service_integration.py::test_repo_search_hint_hit_does_not_skip_broader_results`
   Exit 0: **1 passed in 0.41s**. Candidate-only, not root acceptance.
   Hub broker failed before write (`request_not_sent=true`, `outcome_unknown=false`); one native fallback.
2. Initial overlay command used only root `PYTHONPATH` and `--confcutdir=handoff --rootdir=handoff`.
   Exit 1: **1 failed, 1 passed in 0.64s**. Candidate pytest configuration (`pythonpath=['.','src']`)
   took precedence, loading the older candidate. The stale-hint case skipped broad search.
   This result is NOT root evidence and does not justify a root production change.
3. Corrected root-source overlay, with explicit import-origin guard and unchanged recall assertions:

```powershell
$env:PYTHONPATH='C:\Users\Adam\.local-ai-hub\src'
$env:T21_EXPECT_SOURCE_ROOT='C:\Users\Adam\.local-ai-hub\src'
python -B -m pytest -q -p no:cacheprovider --tb=short -o pythonpath=C:/Users/Adam/.local-ai-hub/src --confcutdir=handoff --rootdir=handoff handoff/test_t21_root_search_recall.py
```

Exit 0: **2 passed in 0.61s**. Real `RepositoryTools` plus persisted current/stale hint,
indexed and undiscovered paths, excluded path, and bounded broader-search invocation.
This is verified root-source overlay evidence; root test-suite execution remains pending integration.

## Integrity and integration

- Root `services.py`: `BAE60B898DB52E078265A2419DC29C3BC08C4311A391279B62C898F7D4C04922`.
- Root `project_config.py`: `6050453FA90C83F0282C4DD2588CAC4454B5187F9C85521CF7AABF089E41C832`.
- Root `repo_tools.py`: `D6EAE9A69059353B1D182A3D1A2D3AF8CF61AA623AC8817B97A121AB9385D07D`.
- Test artifact: `AE78CC07734F382561AD2E65174B5CD133420D371D5DD9124DB4AD5CE362943D`.
- `T21-root-current-search-recall-test.patch`: `922F70F5D922D351CFB26854DD7915D3329D7D8A0D362C1E50C899CC48049271`.
- Updated patch `git apply --check` against exact root: exit 0. Root source hashes unchanged.
- Test slot released after each run. No model, daemon, or root command process started.

Next owner: T20 integrates only the new-test patch and executes
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_search_recall.py`
in root, with `T21_EXPECT_SOURCE_ROOT` set to root/src. Broader T21 consumer acceptance stays open.

## Root integration receipt

T20 applied the exact new-test patch. Orchestrator then verified no competing test process
and ran at `C:\Users\Adam\.local-ai-hub`:

```powershell
$env:PYTHONPATH='src'
$env:T21_EXPECT_SOURCE_ROOT='C:\Users\Adam\.local-ai-hub\src'
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t21_search_recall.py
```

Exit 0: **2 passed in 0.81s**. Root test file SHA-256:
`5E47D47DD21D8F6137A65D52A469753071D5826D6A0711965E14F482546700FD`.
The on-disk root hash differs from the LF patch artifact after Git/Windows line-ending conversion;
the source-origin assertion and unchanged acceptance assertions passed in root.
Only this integration slice is accepted. T21 end-to-end consumer acceptance remains open.
