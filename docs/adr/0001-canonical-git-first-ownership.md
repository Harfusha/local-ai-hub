# ADR 0001: Canonical Git-First Ownership for Agent OS State

## Status
Accepted

## Context
Previously, Agent OS state was maintained in a local SQLite database (`agent_state.sqlite`) per checkout/node.
This caused synchronization drift across independent clones and linked worktrees, dual-authority conflicts,
accidental leaking of local execution leases, private session tokens, and transient credentials into shared contexts,
and prevented deterministic collaboration across distributed developer nodes.

Furthermore, a clean repository clone without the local SQLite database had no way to restore project intent,
active goal contracts, checkpoints, historical verified fixes, or durable project memory.

## Decision
We establish **Git-first single-source-of-truth ownership** for all shared project intelligence under `.local-ai-hub/`:

1. **Canonical Durable Owner (Git-backed)**:
   - Git repository storage under `.local-ai-hub/` is the single authoritative owner of approved, portable, durable records:
     - `.local-ai-hub/project.json` — Project identity, version, schema and mode.
     - `.local-ai-hub/plans/*.plan.json` — Authoritative project plans and goals.
     - `.local-ai-hub/knowledge/{type}/{id}.json` — Requirements, processes, entities, rules, findings, reviews.
     - `.local-ai-hub/agent-os/tasks/{task_id}.json` — Reviewed task goal contracts, portable checkpoints, and lineage.
     - `.local-ai-hub/agent-os/memory/{record_id}.json` — Scoped, durable project memory (excluding session/credential data).
     - `.local-ai-hub/agent-os/incidents/{incident_id}.json` — Resolved operational incidents, signatures, and verified fixes.
     - `.local-ai-hub/agent-os/handoffs/{handoff_id}.json` — Reviewed task handoffs for cross-checkout transfers.
   - Writes to canonical state MUST pass schema validation, secret scanning, content-addressable digests (CAS), and atomic journal commits.

2. **Derived Rebuildable Projections (SQLite)**:
   - The local SQLite database (`agent_state.sqlite`) is demoted from an authoritative owner to a **derived, rebuildable local projection**.
   - A clean checkout or new clone without an existing SQLite database MUST be able to fully reconstruct its local query projections from the canonical Git records via deterministic projection rebuild (`rebuild_agent_state_projection`).

3. **Strict Local Isolation for Private & Transient State**:
   - The following data classes remain strictly private to the local node / checkout and MUST NOT be published into Git:
     - Active execution leases, lock tokens, heartbeat timestamps (`leases`, `lease_waits`).
     - Ephemeral session credentials, bearer tokens, API keys, and environment overrides.
     - Raw event streams (`agent_events`, `agent_snapshots`, `agent_event_cursors`).
     - Unverified, in-flight execution attempts, raw stdout/stderr blobs, and local command IDs.
     - Full-text and vector index state (`agent_memory_fts`, `agent_memory_embeddings`).

4. **Stale Writer Fencing & Cutover Protection**:
   - During cutover and for published record types, writes directly mutating SQLite projection tables without a canonical Git journal transaction are blocked (fenced).
   - Migration from legacy SQLite state into Git-first records is bounded, paginated, and requires immutable snapshot verification and SHA-256 database integrity checks.

5. **Rollback & Disaster Recovery**:
   - Reverting a canonical Git record simply requires reverting the Git commit.
   - The local projection automatically reconciles against Git HEAD, eliminating out-of-sync corruption.

## Consequences
- **Positive**: Clean clones reproduce the complete project state; worktrees share durable context safely; secrets and leases never leak to Git; full auditability and diffability of project intelligence via standard Git tooling.
- **Negative / Trade-offs**: Publishing canonical records incurs structured serialization and validation overhead; SQLite queries require periodic or watcher-driven projection synchronization.
