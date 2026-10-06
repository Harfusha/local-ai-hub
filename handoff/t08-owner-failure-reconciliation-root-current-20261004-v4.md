# T08 root owner-failure reconciliation v4 — 2026-10-04

## Scope and ownership

Root run reported seven failures across T08-owned acceptance files. Reconciliation pins causes and supplies only T08-owned edits:

1. `tests/test_agent_t08_cache_isolation.py` created a TASK record without T05 root/tenant provenance and used unscoped `MemoryStore.get`. Root T05 scope matching correctly requires task ID + root + tenant. Fixture now writes those exact provenance fields and verifies recovery through a fully scoped lookup. No T05 source changed.
2. `tests/test_agent_t08_crash_after_commit.py` and `tests/test_agent_t08_event_page_snapshot.py` expected `AgentEvent` objects. Candidate API returns objects; root `AgentStateStore.event_page` serializes events to dictionaries. Tests now read the same `kind` / `seq` values from either representation; assertions remain exact. No T09 source changed.
3. `src/local_ai_hub/agent_events.py` root `_ALTERNATE_OBJECT_SQL_HASHES` repeats the `agent_incidents` key. Python keeps the later tuple and silently drops two approved legacy fingerprints (`43c461...`, `b3f8fa...`). Patch removes the duplicate one-entry key, retaining the existing three-hash tuple. Expected/current incident fingerprint remains in `_EXPECTED_OBJECT_SQL_HASHES`; migration remains exact-hash allowlisted. This is the T08 AgentStateStore migration-recovery hunk.

No changes to T05-owned memory implementation, T09 verification implementation, `/api/context/pack`, root worktree, or other files.

## Candidate verification

After all fixture/test changes, exact candidate-only command exited 0: `12 passed in 4.13s`.

```powershell
$env:PYTHONPATH=(Join-Path (Get-Location) 'src'); python -B -m pytest -q -p no:cacheprovider --tb=short -W error::ResourceWarning tests/test_agent_t08_cache_isolation.py tests/test_agent_t08_crash_after_commit.py tests/test_agent_t08_event_page_snapshot.py tests/test_agent_t08_migration_recovery.py
```

No root tests run after the owner's 58-pass/7-fail selector. Root patch validation below is static only.

## Root-current pins

Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.

| Root path | Preimage SHA-256 | Candidate post SHA-256 | Candidate LF SHA-256 / expected root source post |
|---|---|---|---|
| `tests/test_agent_t08_cache_isolation.py` | `c132ef4f7ca3ebd6fd072b10c4ac5835501ec6660d23d62f95690697561e8e75` | `79c4846fa86dfb3e69946477cabc4247b21cc0c213430c31e47fab4921f7b840` | `5e29622ec5a8efbd49d74fe81849d34896a5c99e38bfc756784ef3fb0f86bda6` |
| `tests/test_agent_t08_crash_after_commit.py` | `9c949a0cb2d9fc5f58fa7264ef1e8f5def13bb657328998591d0a97918849e8f` | `87fecf3828333c4692ad62a6101149a73dc21e303bf16950a4527c8153bcce66` | `d61ba36bdab1d7eb031fdefc5621bdc753af71fa88c2933a62bde46efddfa183` |
| `tests/test_agent_t08_event_page_snapshot.py` | `32a481ed12f35d309a53e6a2203ffb278837ff6e71e432cff5ac5d582b74ed66` | `15d5c0a0c179776f53ceaca33888335be0e2cf1325628dca8e16bc5ac92b84f2` | `cbaa5226643e1ad15a6105de42769a702ad32020537755f5a8d723962834bcb2` |
| `src/local_ai_hub/agent_events.py` | `1b8e63a5ff329090801cd7f19e7df7a95e42ac0034465ac5fa06d566b279ccf4` | candidate has existing allowlist equivalent; file not edited in this continuation | exact root expected post after duplicate-key removal: `7b79c47e999f172bd21f8cab58534faacc4397cc0cdb6673c5335366897190e8` |

Completion source dependency remains root SHA-256 `6ee041fc54ba05da18ddd542917423216a6010f50bcee2d49a271ee527a77b18`.

## Immutable packet

Patch: `handoff/t08-owner-failure-reconciliation-root-current-20261004-v4.patch`

Patch SHA-256: `448550e09aaf9c4376b0a7f6ba595f4a352c40e8854bc4279f8c3e68b17e40e5`.

Root current `git apply --check --whitespace=error`: exit 0. Patch unapplied; no root tests rerun.
