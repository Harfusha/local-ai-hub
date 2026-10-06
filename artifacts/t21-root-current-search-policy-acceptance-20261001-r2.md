# T21 root-current search policy acceptance r2

## Scope and pinned sources

- Candidate-only controlled overlay; no root or T21 source writes. The runner copies only root `project_config.py`, `repo_tools.py`, and `services.py` into a temporary package, applies the patch, then runs the unchanged main-owned T21 test.
- Root `repo_tools.py` preimage SHA-256: `d6eae9a69059353b1d182a3d1a2d3af8cf61aa623ac8817b97a121ab9385d07d`.
- Root `services.py` preimage SHA-256: `1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1`.
- Unchanged root `project_config.py` SHA-256: `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`.
- Main-owned `tests/test_t21_search_policy_consumers.py` SHA-256: `2d95eceb2b4f3c283af5006633ead8378669bf033bd0781312a50bf3e5de7c1b` (unchanged).
- Patched overlay SHA-256: `repo_tools.py` `a02e067a5c550f43d0cacdeb6c2bf9415be8bd46e4a3febbbd8535ac7538a401`; `services.py` `a06ae015085e4b4dc61bf09a99570332044d65d623b7521218e569c329554235`.

## API and behavior

- `RepositoryTools.search(..., *, project_settings=None)`, `RepositoryTools.search_paths(..., *, project_settings=None)`, and `_path_extension_is_searchable(..., project_settings=None)` accept the resolver's frozen `ProjectSettings` per call. No shared extension set is mutated.
- Custom text extensions reach broad lexical inventory and hinted search. Forced project globs get a bounded walker for gitignored files; visited entries, elapsed time, and returned files are capped.
- Project excludes, binary extensions, maximum size, local config files, ignored hard-denial metadata, symlinks, and out-of-root paths remain denied for forced candidates. Existing ripgrep timeout and repository file limits remain in force.
- `LocalAIServices.repo_search` passes current settings to broad and targeted consumers, applies them while validating hints, and reapplies extension/policy checks to final results. `/api/context/pack` and unrelated service methods are untouched.

## Validation

- Exact command: `python -B handoff/run_t21_search_overlay_acceptance.py`.
- Result: exit 0; main-owned T21 acceptance **5 passed in 1.29s**. Runner verified root preimages, patch postimages, and every loaded module `__file__` inside the controlled overlay.
- Additional bounded guard probe in the same run: broad results exactly `node_modules/@my-org/button.dep`, `src/button.shader`, `src/visible.py`; targeted hints returned only the two permitted custom text files. Explicit exclude, binary, oversize, and outside-root candidates were denied.
- Patch: `handoff/t21-root-current-search-policy-v20261001-r2.patch`; SHA-256 `f74f747c0720ab1df9055de82a3cd37ca049df814c8dd3f94b2f886ce20a6f91`; apply-check and exact postimage hash check passed on copied root preimages.
- `r1` is preserved as a superseded draft; `r2` adds the project-force rule to the targeted ignored-directory admission path.
- Root integration/review remains with T20. No root write, API route edit, or benchmark was performed.
