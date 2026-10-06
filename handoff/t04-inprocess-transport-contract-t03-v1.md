# T04 in-process transport contract for T03 wiring

Status: implementation contract, 2026-10-02
Owner: T04 core transport; T03 owns MCP action schemas and transport selection/wiring.

## Public interface

```python
class InProcessTransport:
    def __init__(self, config_path: str | None = None): ...
    def open(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
        operational_action: str | None = None,
        requires_heavy_work: bool = True,
    ) -> bytes: ...
    def close(self) -> None: ...
```

`HubClient` gains an optional keyword-only `inprocess_transport` implementing this interface. `HubClient.get()` and `.request()` use it instead of `_pooled_open()` when present; default HTTP transport and auto-start behavior remain unchanged when it is absent. They accept optional `operational_action` and `requires_heavy_work` metadata for in-process policy gating. T03 passes both values from its semantic classifier so deterministic reads keep the helper's allowed behavior in restricted modes. No module-level app/services import or construction is added to `client.py`.

T03 wiring shape:

```python
CLIENT = HubClient(
    tenant=TENANT,
    config_path=CONFIG_PATH,
    inprocess_transport=InProcessTransport(config_path=CONFIG_PATH),
)
```

Constructing the transport is lazy; it creates `LocalAIApp` on its first call. T03 passes the semantic action and classifier result in `client.request(..., operational_action=..., requires_heavy_work=...)` / `client.get(..., operational_action=..., requires_heavy_work=...)`. `HubClient.close()` releases the in-process app owned by the injected transport.

## Wire behavior

- Inputs match the existing HTTP client boundary: method/path, exact JSON request bytes, tenant/agent/token/request-ID headers, and timeout.
- The transport calls the existing `http_server.Handler.do_GET()` / `.do_POST()` dispatch in-process through in-memory request/response streams. It opens no HTTP connection and starts no daemon process. Existing Handler authorization, Host/Origin checks, tenant binding, persistent per-tenant rate limiting, payload validation, route dispatch, and response envelope remain authoritative. The HTTP server's bounded handler admission and overload response are mirrored in-process.
- The transport uses `operational_mode_gate_error()` with T03's semantic action and the current state snapshot, after Handler authorization; missing/degraded state fails closed. T03 retains action classification and calls the mode gate before choosing a transport. This avoids deriving MCP policy from API paths.
- A 2xx response returns the same response-body bytes as HTTP. An HTTP error status raises `urllib.error.HTTPError` with status, headers, and response body, preserving `HubClient`'s structured error parsing and retry behavior.
- A timeout before route dispatch marks the request not sent and prevents later dispatch. A timeout after dispatch raises a socket-compatible timeout; as with a disconnected HTTP client, already-dispatched service work may continue. Explicit cancellation actions still travel through the same route and remain service-owned.
- `close()` is idempotent; it shuts down only the in-process `LocalAIApp` owned by this transport. It never stops an external daemon.

## Ownership boundaries

- T04 may edit only `client.py`, add `inprocess_transport.py`, add focused transport/client tests, and this handoff.
- T03 changes `mcp_server.py` to choose/inject this transport and remains sole owner of action schemas/wiring in `operation_contracts.py`.
- Do not edit root checkout, `http_server.py`, `operation_contracts.py`, or `/api/context/pack`.

## Acceptance evidence planned

- Daemon-off MCP call reaches an existing service route through this transport.
- Guarded test proves no HTTP connection and no child-process spawn.
- Auth/policy rejection, invalid action/payload schema, operational-mode block, structured HTTP errors, request timeout, and explicit cancellation route retain existing semantics.
- Run focused tests only after T02 releases the shared test slot.
