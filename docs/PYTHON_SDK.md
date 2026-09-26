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

`get()` and `post()` accept per-call timeouts in seconds. The defaults are 15 seconds and 360 seconds, subject to the configured client timeout ceiling. Calls return dictionaries. Check `success`, `error`, `terminal`, and `retryable`; if a mutation returns `outcome_unknown: true`, its effect is not known, so inspect state before retrying.

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
| Resume a task | `client.coord("task_resume", task_id=task_id)` | `POST /api/agent-state/tasks` with action `resume` | Mutates task state; requires Agent OS enabled |
| Look up evidence | `client.get_evidence(evidence_id, verify=True)` | `POST /api/evidence/get` with `evidence_id`, `verify` | Read-only; verification checks evidence freshness |

Track first-call success, actual HTTP request count, and whether each error tells the caller if retry is safe. The route contract tests exercise SDK payloads through the production HTTP handler in [test_client_sdk_routes.py](../tests/test_client_sdk_routes.py); conversation payload mapping is covered by [test_conversation_continue_route_contract.py](../tests/test_conversation_continue_route_contract.py).
