# T08 coordination identity consumer handoff

## Contract

- T21 resolves a trusted opaque `ProjectContext.coordination_id`. T08 does not derive it, accept it from a request body, or treat it as a filesystem path.
- `MemoryStore.find_for_context` keeps the current physical-root predicate and adds one repository-only shared branch requiring a nonempty request root, exact tenant, and matching stored `provenance.repository_id`.
- Legacy root-only records stay visible at the exact physical root. There is no global/unscoped OR branch. Returned shared records retain their original `scope_id` and `provenance.root`.
- TASK, WORKTREE, and BRANCH remain local. Stale-source checks, HTTP get/delete, and source mutation use the physical root and tenant.
- Repository writes replace client provenance identity with the ID from server ProjectContext. HTTP context compilation passes that same trusted identity into ContextCompiler and task-memory adoption.

## Candidate files owned by T08

- `src/local_ai_hub/agent_memory.py`: bounded repository-only SQL sharing branch.
- `src/local_ai_hub/agent_context.py`: trusted context request field and compiler pass-through.
- `src/local_ai_hub/task_context.py`: only ProjectContext can populate the request identity; client fields are ignored and physical roots must match.
- `src/local_ai_hub/agent_tasks.py`: task adoption resolves identity from ProjectContext and fails back to physical-root-only scope.
- `src/local_ai_hub/http_server.py`: server resolver wiring, provenance binding, client-ID rejection, and source-root/tenant-gated repository deletion.
- `tests/test_t08_coordination_identity.py`: share/isolation, legacy, local-scope, physical stale, record-write, request-builder, and real HTTP forged-ID coverage.

## Validation

Candidate command included the new suite and existing adoption/incident/app-wiring selectors: **23 passed in 15.21s**, exit 0. Initial RED was an API-level `TypeError` on the missing trusted `coordination_id` argument; green followed after the bounded consumer bridge.

The HTTP test uses a real `LocalAIApp` and handler but injects a test ProjectContext through the server resolver seam because this T08 candidate does not contain T21's `project_config.py`. T21 is already integrated in the root according to the parent task; root-specific integration and validation remain T20-owned. Do not copy the simplified candidate `task_context.py` over T20's newer ProjectContext-aware implementation; port its trusted `coordination_id` assignment into that root version.

No root files, commits, or T20-owned test slots were changed or used here.
