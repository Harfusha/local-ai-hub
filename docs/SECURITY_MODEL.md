# Security model

The Hub binds to `127.0.0.1` by default. A non-loopback bind requires `security.allow_remote = true` and `security.api_token` with at least 16 characters. On loopback, an empty token leaves HTTP data/control routes unauthenticated; when configured, send it in `X-LocalAI-Token` or `Authorization: Bearer`. `/health` and the dashboard shell are public; other data/control routes require the configured token. T13 auth/root isolation is not integrated in this candidate.

## Identity and shared state

The current candidate does not implement `allowed_roots` or principal-to-root tenant derivation. Repository `root` identifies the requested path; it is not validated as an authorization boundary. MCP repo/RAG actions usually map omitted or `.` roots to MCP `cwd`; preprocessing alone requires an explicit absolute root.

HTTP tenant scope uses caller-provided `X-LocalAI-Tenant`, then `X-Tenant-ID`, then `http-default`. Browser routes bind to their configured browser tenant when an API token is configured. Tenant labels do not authenticate callers and are not derived from repository roots.

Workspace memos are intentionally shared by canonical workspace and memo key. Reads and searches ignore the tenant label, and a later write to the same workspace/key replaces the earlier value when no expected version is supplied; the stored tenant records who supplied the current value. A memo writer may supply the per-key generation it read to reject a stale overwrite. Deletion retains and advances that generation to prevent stale delete-and-recreate writes. A tenant-filtered delete selects a matching memo but does not authenticate the caller. Agent leases live in shared local coordination state. Tenant labels influence lease conflict and owner checks, but they are caller-supplied and are not proof of identity; another caller able to choose a label can impersonate it.

Configure `api_token` when HTTP data/control routes need token authentication, including on loopback. The current token is one shared API secret; per-token permissions and principal namespaces are not implemented.

Root-derived principal/effective-tenant scoping applies to the specified root-scoped memory/task paths only. It does not prove hostile-user isolation for every caller sharing this state directory. Use a separate Hub instance and state directory per trust domain until every private state surface has a confirmed identity-binding contract.

Repository paths, RAG/index databases and exported bundles may contain sensitive source-derived information. Telemetry intentionally excludes prompts, source and model output, but operational logs can still contain paths and error metadata.

The command broker is allowlist/fail-closed and is not a general shell sandbox. The dashboard uses the same policy. Hub-managed Serena processes are constrained by project roots, timeouts, bounded sessions and process-tree termination. CodeGraphContext is standalone external CLI/MCP tooling and follows its own process and security controls.

Report vulnerabilities according to `SECURITY.md`.
