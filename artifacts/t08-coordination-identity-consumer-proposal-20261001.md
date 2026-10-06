# T08 memory consumer boundary for ProjectContext coordination identity

## Seam

T21 owns `ProjectContext.coordination_id`: a server-resolved opaque identifier derived from the Git common directory and configured `shared_namespace`. Invalid configuration yields `None`. The physical project root remains the real worktree path. T08 does not derive or persist a second namespace identity.

Consumer seam: add an optional trusted `coordination_id` to the context request and existing bounded `MemoryStore.find_for_context` call. HTTP context compilation resolves `ProjectContext` on the server from the physical request root. The request builder takes identity only from that object; a client `coordination_id` or `repository_id` never authorizes sharing. Repository writes replace client provenance identity with the resolved `ProjectContext` value in the existing `provenance.repository_id` field.

## Scope rules

- `GLOBAL`: preserve existing tenant rules.
- `REPOSITORY`: return exact-physical-root records, plus records whose existing `provenance.repository_id` equals the same nonempty trusted `coordination_id` and whose tenant matches exactly. The shared branch requires a nonempty physical request root and never treats the ID as a root. Legacy rows without `repository_id` remain visible only at their exact physical root; there is no unscoped fallback or foreign-tenant branch. Keep each shared record's original `scope_id` and provenance `root`.
- `TASK`, `SESSION`, `CLONE`, `WORKTREE`, and `BRANCH`: keep current exact local identity and physical-root checks. `coordination_id` never widens these scopes.
- Missing/invalid project configuration (`coordination_id is None`) disables cross-worktree sharing; exact physical-root retrieval still works.
- `ContextCompiler` and task-memory adoption pass only the server-resolved identity to the same SQL filter. HTTP/MCP payloads cannot provide an authorization ID. `get`/`find` by record identity and correction/deletion remain source-root and tenant scoped; shared context visibility does not rewrite provenance or authorize source mutation from another worktree.
- Event publication/replay and tombstones are outside this memory lookup bridge and must retain their own existing idempotency/transaction rules; this change adds no second store, namespace table, or event identity.
- Stale transitions, volatile source checks, and file resolution continue to use each record's physical root and the current physical worktree. A coordination ID is not a filesystem root.

## Tests in `tests/test_t08_coordination_identity.py`

1. Same opaque ID + same tenant shares repository memory across distinct physical worktrees; unrelated repo, tenant, namespace ID, missing ID, and legacy root-only records do not. Returned record retains source root.
2. TASK, WORKTREE, and BRANCH records remain local when their repositories share a coordination ID.
3. Stale invalidation of a shared project applies only to records at the physical worktree root whose source changed.
4. Request builder and HTTP context compilation ignore client-supplied IDs; server `ProjectContext` controls the identity. Repository writes replace client provenance IDs.

Each isolated store test owns one temporary database and one `AgentStateStore`/`MemoryStore`. The HTTP negative case uses one real app/server path with a server-resolved test context and a client-forged competing ID. No duplicate store is introduced.
