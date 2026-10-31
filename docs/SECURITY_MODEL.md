# Security model

The Hub binds to `127.0.0.1` by default and rejects non-loopback binds. `/health` and the dashboard shell are public. By default with no tokens configured, local loopback clients are trusted. When credentials (`security.api_token`, `supervisor_token`, or `action_tokens`) are configured, protected HTTP routes enforce authentication and fail closed unless a valid credential grants the route's permission. Send credentials in `X-LocalAI-Token` or `Authorization: Bearer`.

`security.api_token` is the service credential and uses `api_token_permissions` for its coarse role grants. `security.supervisor_token` grants only `admin:read` and `admin:write`. `security.action_tokens` maps exact action names to narrowly scoped credentials. `security.users`, `security.api_token_tenant`, and `security.api_token_principal` are removed and reject by presence. API, supervisor, and action token values must be unique. Configured credentials are redacted from diagnostic config views.

## Identity and shared state

Repository/RAG MCP actions reject omitted or `.` roots at the adapter boundary, and preprocessing requires an explicit absolute root. With `api_token` configured, repository roots must resolve inside `allowed_roots`; the root is a physical path boundary, separate from logical coordination IDs. Source behavior does not establish installed-runtime acceptance.

The HTTP server rejects retired `X-LocalAI-Tenant` and `X-Tenant-ID` headers, and retired tenant fields in bodies and queries reject by presence. Authentication uses configured credentials and route permissions; no principal or tenant selector is exposed.

Workspace memos are shared by canonical workspace and key. A later write replaces the earlier value when no expected version is supplied; writers may provide the per-key generation they read to reject a stale overwrite. Deletion retains and advances that generation to prevent stale delete-and-recreate writes. Agent leases use explicit actual writer owners and preserve conflict and fencing checks.

Configure `api_token` to authenticate protected HTTP routes, including on loopback. `api_token_permissions` restricts coarse roles; `supervisor_token` and `action_tokens` retain their documented administrative and action-specific grants. `allowed_roots` limits repository paths.

`HubClient` and the HTTP server preserve explicit root, task, and session identities; none derives a tenant from credentials or workspace labels. Client-side checks do not replace server authorization. Source integration and offline data conversion are distinct from installed-runtime acceptance.

Repository paths, RAG/index databases and exported bundles may contain sensitive source-derived information. Telemetry intentionally excludes prompts, source and model output, but operational logs can still contain paths and error metadata.

The command broker is allowlist/fail-closed and is not a general shell sandbox. The dashboard uses the same policy. Hub-managed Serena processes are constrained by project roots, timeouts, bounded sessions and process-tree termination. CodeGraphContext is standalone external CLI/MCP tooling and follows its own process and security controls.

Report vulnerabilities according to `SECURITY.md`.
