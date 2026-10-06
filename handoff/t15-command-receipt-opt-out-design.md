# T15 receipt persistence opt-out design handoff

Status: design proposal only. No source API, broker, service, or orchestrator code changed. `commands.py` is T06-owned; workflow receipt ownership is T16-owned.

## Finding

T09 reports duplicate persistence along `WorkOrchestrator -> CommandBroker`: the broker auto-persists a command verification receipt when `task_id=work_id` is present, and T16 also records the command result. The task ID is still needed by per-task budgets and must not be removed. This is a T09 owner-reported finding; no new test or runtime receipt was produced by T15.

## Preferred ownership rule

Exactly one component persists each command verification receipt. Prefer reusing the broker-created receipt if T16 can associate it with its step/work record without writing a second verification receipt. This needs no broker API expansion.

If T16 must remain the workflow receipt writer, expose an explicit opt-out at the broker boundary, defaulting to current behavior:

```python
CommandBroker.run(
    command,
    cwd,
    tenant=tenant,
    task_id=work_id,                 # keep budget and task attribution
    record_verification=False,       # suppress broker receipt persistence only
)
```

`record_verification=True` remains the default for all current callers. T16's latest handoff says T06 has been asked to confirm this exact opt-out name. The option must suppress only the broker's receipt write; it must not change `task_id`, budget accounting, execution, timeout/cancel semantics, cache/single-flight behavior, returned command result, or receipt creation by T16. If `run_project_command` or `LocalAIServices.command` forms the T16 path, the option must be explicitly propagated end to end or rejected; do not silently swallow it.

## Ownership and acceptance

- T06 decides and implements any `CommandBroker` API change in its owned `commands.py` scope. T15 will not edit `commands.py`. T06 was asked to confirm `record_verification=False`.
- T16 decides whether the broker or orchestrator owns the single durable command receipt and updates its owned call path if needed. Its latest report says it updated `WorkOrchestrator` verification-store wiring; pytest remains pending.
- T09 confirms the receipt ID/schema semantics and verifies that opting out does not erase task-budget attribution.
- Add regressions for default auto-persist, opt-out with `task_id` retained, exactly one durable receipt in the T16 flow, and budget attribution unchanged. Run them only under T20's explicit validation slot.

Open decision for T06/T16: can T16 reuse the broker's receipt ID/result, or does it require `record_verification=False`? Until owners answer, this is not an approved API and no implementation should be inferred from the example.
