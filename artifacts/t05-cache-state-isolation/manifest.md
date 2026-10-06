# T05 cache/state isolation patch

Patch: `t05-cache-state-isolation-root.patch`
SHA-256: `c042a77ad123e12dedbf898fd2bf7ce256eafce37ca86aaac6cd34e3b6e91f69`

## Expected current dirty root
- HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- Existing untracked target test `tests/test_t05_cache_state_isolation.py`: SHA-256 `cc2bbc3f49fde2f510c215cdcc38e1f0a07137c7c1856f990c68e4d21692ed22`
- Untouched dirty `src/local_ai_hub/agent_events.py`: SHA-256 `9093100c41fcf3fbf1c71577f0f3587026cfc43d1cc229dcc0c435225dc57bea` (current root; T08 migration integration is outside the patch allowlist)
- Untouched dirty `src/local_ai_hub/app.py`: SHA-256 `851d31baab1fe11625004c0e5fddd4fed484a17981c3cce28f925219b29f0655`
- `src/local_ai_hub/cache.py`: SHA-256 `e69ac756c8df9fc21d5e2a5ef57d3670be307be50285d6c12f935ccd693c29cf` (same T05/root implementation).

## Scope and validation
Only `tests/test_t05_cache_state_isolation.py` changes. It asserts cache/state path separation, verifies durable task/event/memory/receipt/lease records after recovery and restart, covers post-initialization corruption, and adds a subprocess recovery followed by `os._exit(73)`.

Root-source scratch run: 5 passed in 10.14s. T05 focused suites (cache isolation, migrations, events, tasks, e2e): 48 passed in 47.16s. `git apply --check` against the current dirty root: exit 0. Root files were not modified.

Root stores durable Agent OS data at `agent_state.sqlite3`; cache users open `cache.sqlite3` in the same state directory. These are separate SQLite files. Cache recovery quarantines/recreates only the cache path and its WAL sidecars.

T05's separate migration-classifier adjustment remains in its existing T05 worktree; it is not part of this root patch because root has a different `agent_events.py` baseline. No T08 schema files or `/api/context/pack` paths are included.
