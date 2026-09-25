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

`get()` and `post()` accept per-call timeouts in seconds. The defaults are 15 seconds and 360 seconds, subject to the configured client timeout ceiling. Calls return dictionaries. Check `success` and `error`; if a mutation returns `outcome_unknown: true`, its effect is not known, so inspect state before retrying.
