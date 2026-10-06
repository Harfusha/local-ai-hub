# T05 post-callsite root failure diagnosis — 2026-10-01

## Reported root batch

T20 reported 3 failed, 60 passed in 29.07s after T08 API fix plus T05 cursor-callsite patch.

1. `test_mark_stale_for_revision_preserves_metadata_and_emits_event` and `test_mark_stale_for_revision_guards_revision_paths_root_and_repeats` queried legacy stream IDs (`memory:repository:<key>`). T05 now writes to canonical length-prefixed stream IDs. Candidate test queries now use the canonical key; both event-presence/count assertions remain unchanged.
2. `test_memory_delete_requires_matching_scope_identity` failed because `get(scope=WORKTREE, scope_id=...)` returned no row before authorized delete. `find()` applied its no-root fallback (`GLOBAL OR empty provenance root`) even for explicit non-repository identity scope. The worktree row had a root in provenance, so exact scope-id lookup was hidden. Narrow fix exempts explicit identity scopes with `scope_id`; root/repository guard remains. Tenant filters remain.

## Minimal root patch

`artifacts/t05-root-event-and-scope-fix.patch`, SHA-256 `835ADDAD88BE3256079F31FA1C999AC639066749B102F388D09D5069405B262F`. It changes one root filter condition and updates two stale-event stream queries without weakening event assertions. `git apply --check` against root passed. Root was not modified.

## Candidate verification

T05 source/tests overlaid with current root T08 `agent_events.py` and `sqlite_support.py`.

Command after overlay setup: `PYTHONPATH=<overlay>\src python -m pytest -c <overlay>\pytest.ini -q --tb=short -p no:cacheprovider <four selectors>`.

Selectors: stale metadata/event, stale path/root/repeat guard, `test_memory_find_enforces_root_repository_and_tenant_identity`, `test_memory_delete_requires_matching_scope_identity`.

Result: **4 passed in 1.03s**. Candidate source SHA-256 `C89740E1DA1D7C02DDB7C30F46C42C188104516B1A295883C4B50551CB9CCCDE`; candidate test SHA-256 `CEBA9D3DF9B9882533BD2894D291F06BB368997AFFDA0A87699D56111E0CC628`.

No root test was run by T05 after the reported root batch.

## GLOBAL memory identity follow-up — 2026-10-01

Current contract from T20: preserve GLOBAL GET/list/context tenant filtering. Shared GLOBAL provenance is tenantless. Tenant-owned GLOBAL records remain visible only to matching tenant during GET/find. Explicit GLOBAL DELETE remains transport-tenant agnostic; root/repository identity guards still apply. No production retrieval change requested.

T20 already corrected root `tests/test_agent_state_transport.py` fixture by removing `tenant=legacy-tenant`; no competing root patch is needed. T20 owns exact root HTTP/context selectors. T08 owns shared test slot; focused candidate selectors wait for release.

The earlier 5-pass result in this section used an intermediate, now reverted GLOBAL retrieval/delete policy. Treat that receipt and `t05-global-memory-identity-root-current.patch` as superseded. Current candidate `agent_memory.py` retains tenant filtering; fresh focused receipt pending slot release.
