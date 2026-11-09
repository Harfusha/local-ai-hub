# Security model

The Hub binds to `127.0.0.1` and rejects non-loopback peers before routing. Loopback HTTP/MCP calls need no Hub API token; the Hub has no bearer-token authentication system. Dashboard mutations still require same-origin browser checks. Command authorization, capabilities, root confinement, approvals, leases, rate limits, and audit records remain enforced.

Retired `security.api_token`, `security.supervisor_token`, `security.action_tokens`, and `security.api_token_permissions` keys reject by presence. Retired user, tenant, and principal fields also reject by presence. OpenCode's separate nonce-scoped provider-session credential authenticates only that provider bridge; it is not a Hub credential.

## Identity and shared state

Repository/RAG MCP actions reject omitted or `.` roots at the adapter boundary, and preprocessing requires an explicit absolute root. Configured `allowed_roots` confines repository roots; the root is a physical path boundary, separate from logical coordination IDs. Source behavior does not establish installed-runtime acceptance.

The HTTP server rejects retired `X-LocalAI-Tenant` and `X-Tenant-ID` headers, and retired tenant fields in bodies and queries reject by presence. Loopback is the network trust boundary; caller-supplied headers do not grant authority.

Workspace memos are shared by canonical workspace and key. A later write replaces the earlier value when no expected version is supplied; writers may provide the per-key generation they read to reject a stale overwrite. Deletion retains and advances that generation to prevent stale delete-and-recreate writes. Agent leases use explicit actual writer owners and preserve conflict and fencing checks.

`allowed_roots` limits repository paths. Loopback access does not remove command authorization, capabilities, approval gates, writer leases, rate limits, or audit requirements.

`HubClient` and the HTTP server preserve explicit root, task, and session identities; none derives a tenant from credentials or workspace labels. Client-side checks do not replace server authorization. Source integration and offline data conversion are distinct from installed-runtime acceptance.

Repository paths, RAG/index databases and exported bundles may contain sensitive source-derived information. Telemetry intentionally excludes prompts, source and model output, but operational logs can still contain paths and error metadata.

The command broker is allowlist/fail-closed and is not a general shell sandbox. The dashboard uses the same policy. Hub-managed Serena processes are constrained by project roots, timeouts, bounded sessions and process-tree termination. CodeGraphContext is standalone external CLI/MCP tooling and follows its own process and security controls.

Report vulnerabilities according to `SECURITY.md`.
