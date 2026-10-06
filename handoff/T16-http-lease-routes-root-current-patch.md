# T16 HTTP lease routes root-current patch

Patch: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-http-lease-routes-root-current.patch`
SHA-256: `F22B5290486857EAC823F408B4558C89A308180B26C193EA0F8D6B7B5D9A6D0B`

## Scope

- Server derives namespace from `ProjectContext.coordination_id` using request root and configured state directory.
- GET `/api/leases` passes server identity to list and waits.
- POST `/api/leases/claim` and `/api/leases/claim_batch` pass server identity; payload `coordination_id` is ignored.
- Adds real loopback HTTP acceptance for linked A/B collision, unrelated C isolation, malformed identity fail-closed, namespace waits, SQLite reload, and owner renew/release.
- No auth, frontdoor, journal, T18, MCP, client, memory, or context-pack changes.

## Apply prerequisites

- Root `http_server.py` preimage SHA-256: `CD2998708AFBEE64A22D8027AA86969E9C17A05967CBED8431BEE7A4F8D55FD5`.
- Candidate HTTP acceptance test SHA-256: `D560EC58FD1250881D6D9241D6B2C6CE8A0E119F87B1C9C1CE809D97954363C2`.
- Apply namespace patch first: `T16-namespace-root-current.patch` supplies namespace-aware `ScopeLeaseStore.claim_batch`, `list`, and `waits` APIs. This patch includes no `leases.py` hunk to avoid overlapping ownership.
- T20 remains root integrator. Patch is un-applied.

## Evidence

- Route test: `1 passed` in 5.60s.
- Focused T16 suite: `62 passed, 1 skipped, 1 deselected` in 49.62s. Skip: Windows symlink privilege `WinError 1314`. Deselection: real T06 broker selector.
- Root write: none.
