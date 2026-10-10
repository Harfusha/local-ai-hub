# Security model

The Hub binds to `127.0.0.1` by default and rejects non-loopback binds. `/health` and the dashboard shell are public. Protected HTTP routes fail closed unless a configured credential grants the route's permission. Send credentials in `X-LocalAI-Token` or `Authorization: Bearer`.

`security.api_token` is the service credential and uses `api_token_permissions` for its coarse role grants. `security.supervisor_token` grants only `admin:read` and `admin:write`. `security.action_tokens` maps exact action names to narrowly scoped credentials. `security.users` maps user names to `{ token, permissions, tenant? }`; permissions are exact `resource:read` or `resource:write` scopes. API, supervisor, action, and user token values must be unique. Configured credentials are redacted from diagnostic config views.

## Identity and shared state

Repository/RAG MCP actions reject omitted or `.` roots at the adapter boundary, and preprocessing requires an explicit absolute root. `allowed_roots` and principal-to-root tenant derivation still do not establish an authorization boundary here: repository `root` identifies the requested path, but server-enforced root isolation remains unverified.

HTTP tenant scope uses caller-provided `X-LocalAI-Tenant`, then `X-Tenant-ID`, then `http-default`. Browser routes bind to their configured browser tenant when an API token is configured. Tenant labels do not authenticate callers and are not derived from repository roots.

Workspace memos are intentionally shared by canonical workspace and memo key. Reads and searches ignore the tenant label, and a later write to the same workspace/key replaces the earlier value when no expected version is supplied; the stored tenant records who supplied the current value. A memo writer may supply the per-key generation it read to reject a stale overwrite. Deletion retains and advances that generation to prevent stale delete-and-recreate writes. A tenant-filtered delete selects a matching memo but does not authenticate the caller. Agent leases live in shared local coordination state. Tenant labels influence lease conflict and owner checks, but they are caller-supplied and are not proof of identity; another caller able to choose a label can impersonate it.

Configure `api_token` when HTTP data/control routes need token authentication, including on loopback. The current token is one shared API secret; per-token permissions and principal namespaces are not implemented.

`HubClient` preflights the specified root-scoped memory/task paths using configured allowed roots, a principal, and an HMAC-derived tenant. The HTTP server's `_tenant` still uses caller-provided labels outside token-bound browser routes; client preflight is not server authorization. Operational-mode and scoped admin-action-token code are present. Full HTTP root isolation remains unverified. Use a separate Hub instance and state directory per trust domain until every private state surface has a confirmed identity-binding contract.

Repository paths, RAG/index databases and exported bundles may contain sensitive source-derived information. Telemetry intentionally excludes prompts, source and model output, but operational logs can still contain paths and error metadata.

The command broker is allowlist/fail-closed and is not a general shell sandbox. The dashboard uses the same policy. Hub-managed Serena processes are constrained by project roots, timeouts, bounded sessions and process-tree termination. CodeGraphContext is standalone external CLI/MCP tooling and follows its own process and security controls.

Report vulnerabilities according to `SECURITY.md`.
