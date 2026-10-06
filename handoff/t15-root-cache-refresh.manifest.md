T15 cache-freshness handoff

- Base root: `C:\Users\Adam\.local-ai-hub`
- Base HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- Base blob `src/local_ai_hub/commands.py`: `a1a2112ec89aade3bb68ae4c222a50f13829bcc4`
- Base blob `tests/test_command_concurrency_contract.py`: `edd5f1433ea2dd992190e2b841b5a58c5b994f8e` (read-only; not patched)
- Allowlist: `src/local_ai_hub/commands.py`, `tests/test_command_cache_freshness.py`
- Patch: `handoff/t15-root-cache-refresh.patch`
- Root mutation: none; only `git apply --check` authorized.
- Behavior: invalidate cached repository fingerprint only after a result-cache candidate exists, recompute command key, and return result only if a valid cache entry still exists for refreshed key.
- Existing fefe changes in `commands.py`, inherited T06 changes in `process_utils.py`, mixed `tests/test_command_concurrency_contract.py`, and T15 benchmark file are excluded.
- Validation: `git apply --check` against the current root passed; root checkout status and `commands.py` blob hash remained unchanged.
- Focused test: `tests/test_command_cache_freshness.py` passed (`1 passed in 1.09s`) using an ephemeral copy of the current root package with this patch applied. Temporary candidate was removed automatically.
