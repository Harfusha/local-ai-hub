# T10 root-current consumer callgraph receipt r1

- Scope: isolated T10 candidate fixture; no root writes. The root `project_config.py` and `services.py` were loaded from the root checkout inside a temporary Git repository and linked worktree; the test asserts each imported `__file__` and exact SHA-256.
- Command: `$env:PYTHONPATH='src'; $env:T10_ROOT_REPOSITORY='C:\Users\Adam\.local-ai-hub'; python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_project_config_consumers.py::test_candidate_consumers_with_real_root_project_config`
- Result: exit 0; **1 passed in 5.31s**.
- Root preimages used: `project_config.py` `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`; `services.py` `1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1`.
- Receipt included primary/project/worktree inheritance, path-hint revision and config invalidation, blocked excluded repository-search hints, stale excluded-ref removal, full inventory on config change, `.pyx` watcher admission, Python parser selection, linked and Gemini seed preservation, and diagnostic baseline persistence.
- New regression asserts that a configured `.pyx` file produces the `caller -> target` AST call edge through `CodeIndex.find_callers`; selector passed with that assertion active.
- Immutable delta patch: `handoff/t10-root-current-callgraph-regression-v20261001-r1.patch`; patch SHA-256 `0284186c776365ddd9e70065420a83d069281b9bc947bfaac8795574a69704c9`; candidate test postimage SHA-256 `478aac65426603f0bca73eaff96121f4b6ab8edc93d1478431e83b39dcc7dff0`.
- Separate search fallback metric and ripgrep-timeout behavior remain covered by the previously recorded focused candidate command; no new 100k run here.
- 100,000-file candidate/baseline pair remains pending T20's exclusive CPU slot. No speedup claim.
