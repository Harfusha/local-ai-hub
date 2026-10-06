# T08 blackboard context boundary

Source review found `ContextCompiler.compile` auto-reads task, `task:<id>`, `swarm:<id>`, and `global` boards. `BlackboardStore.get` returns shared sections without tenant, repository root, revision, or validity arguments. The compiler previously emitted those sections at confidence 1.0 with no provenance.

Global collaboration is an existing blackboard behavior. Evidence does not establish a malicious tenant exploit. Context compiler now labels automatic board content as unverified shared collaboration data, adds a warning to verify against tenant/repository-scoped evidence, sets confidence to 0.25, and attaches board/section/author/version provenance. Board CRUD and persisted data remain unchanged. No new memory system added.

Focused real-store test uses one AgentStateStore, MemoryStore, BlackboardStore, ContextCompiler, and TaskStore. It checks compile plus task create/resume: current-root/current-tenant memory stays visible; foreign repository, foreign tenant, and stale facts stay absent; global board data remains readable but enters context only with unverified labeling.

Validation: `tests/test_agent_task_memory_adoption.py` and `tests/test_agent_context.py`: 29 passed. `tests/test_t08_coordination_identity.py` and `tests/test_async_inference_admission.py`: 11 passed. Combined root-current patch passed `git apply --check`; root was not modified.

Patch: `t08-root-current-identity-inference-blackboard.patch`.
