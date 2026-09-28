# Python client

`HubClient` is a synchronous Python client for the Local AI Hub HTTP service. Install and configure Local AI Hub first. From a source checkout, install the package with `python -m pip install .`.

Import the client from its current public module path:

```python
from local_ai_hub.client import HubClient

client = HubClient(tenant="example-agent", auto_start=False)
try:
    result = client.status(detail="brief")
    if result.get("success") is False:
        raise RuntimeError(result.get("error", "Local AI Hub request failed"))
    print(result)
finally:
    client.close()
```

With `config_path` omitted, the client uses `LOCAL_AI_CONFIG`, then the installed user config at `~/.local-ai-hub/config.toml` when present. Set `auto_start=True` (the default) if the client may start the local service; use `False` when a service manager owns startup.

`get()` and `post()` accept per-call timeouts in seconds. The defaults are 15 seconds and 360 seconds, subject to the configured client timeout ceiling. Calls return dictionaries. Check `success`, `error`, `terminal`, and `retryable`; HTTP errors preserve server error text while normalizing status/retry fields. Follow [Failure recovery](#failure-recovery) for recommended next steps. If a mutation returns `outcome_unknown: true`, its effect is not known, so inspect state before retrying.

## One-call workflows

Each convenience method below maps one client call to one endpoint. The transport may replay only operations marked safe by its retry policy. `coord()` remains the general route for coordination actions not listed here.

Convenience methods use `post()`'s 360-second default timeout, subject to the configured ceiling. Use `post()` directly when a workflow needs a custom per-call timeout.

| Goal | Python call | HTTP mapping | Effect / availability |
|---|---|---|---|
| Find callers | `client.callers(root, symbol, limit=50)` | `POST /api/repo/callers` with `root`, `symbol`, `limit` | Read-only code-index lookup |
| Get repository context | `client.context_pack(root, query, max_tokens=4200, mode="adaptive")` | `POST /api/context/pack` with the supplied context options | Read-only; unavailable optional backends degrade to deterministic/lexical evidence |
| Verify a change | `client.verify_receipt(task_id, criterion, evidence_id=...)` | `POST /api/agent-state/verification` with action `receipt` | Writes a durable verification receipt; requires Agent OS enabled |
| Continue a conversation | `client.continue_conversation(conversation_id, prompt)` | `POST /api/conversations/continue`; `prompt` maps to `task` | Updates conversation state and may require an available model runtime |
| Cancel an async job | `client.cancel_job(job_id)` | `POST /api/async-jobs` with action `cancel` | Mutates job state; job may already be terminal |
| Resume a task | `client.coord("task_resume", task_id=task_id)` | `POST /api/agent-state/tasks` with action `resume` | Sets task status to `ACTIVE` and preserves checkpoint metadata; does not restore workspace files. Requires Agent OS enabled |
| Look up evidence | `client.get_evidence(evidence_id, verify=True)` | `POST /api/evidence/get` with `evidence_id`, `verify` | Read-only; verification checks evidence freshness |

## Scenario evidence

The production-handler fixtures below measure the first direct SDK call and exact HTTP `POST` count for each successful workflow. They verify request mapping and retry flags; they are not a human usability study. The context case uses `mode="fast"` with a stubbed service, so it does not measure retrieval quality or live optional-backend availability.

| Workflow | First-call result | HTTP `POST` requests | Evidence |
|---|---|---:|---|
| Find callers | success | 1 | `test_sdk_convenience_methods_map_to_production_http_handlers` |
| Get repository context | success | 1 | `test_sdk_convenience_methods_map_to_production_http_handlers` |
| Cancel async job | success | 1 | `test_sdk_convenience_methods_map_to_production_http_handlers` |
| Look up evidence | success | 1 | `test_sdk_convenience_methods_map_to_production_http_handlers` |
| Continue conversation | success | 1 | `test_hub_client_continues_through_production_route_and_preserves_transcript` |
| Resume task | success | 1 | `test_sdk_resume_and_verification_use_real_agent_state_handlers` |
| Verify change | success | 1 | `test_sdk_resume_and_verification_use_real_agent_state_handlers` |

Fixture total: **7/7 successful workflows on first direct call; 7 HTTP requests total**. Error fixtures assert machine-readable retry guidance: invalid context mode returns `terminal=true`, `retryable=false`, and `context mode must be adaptive, full or fast`; expired conversation returns `terminal=true`, `retryable=false`, and `conversation not found`; a competing continuation returns `in_progress=true`, `retryable=true`. These assertions do not measure whether a human caller finds the wording clear. Reproduce with `python -m pytest -q --tb=short tests/test_client_sdk_routes.py tests/test_conversation_continue_route_contract.py`.

## Failure recovery

- Invalid context mode. Choose `adaptive`, `full`, or `fast`; do not resend the invalid value. The result is terminal (`terminal=true`, `retryable=false`).
- We could not find this conversation. Check its ID. If it expired, start a new conversation and continue there. The result is terminal (`terminal=true`, `retryable=false`).
- A continuation is already running. Wait for it to finish; do not send a duplicate request. The result is retryable and marked in progress (`in_progress=true`, `retryable=true`).
- `outcome_unknown: true`: the client cannot confirm a mutation's effect. Inspect current task or job state before retrying.

Task resume reactivates task state and keeps its checkpoint metadata. It does not restore workspace files. These are recommended caller explanations; human clarity remains unmeasured.
