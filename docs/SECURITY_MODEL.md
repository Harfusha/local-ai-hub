# Security model

Local AI Hub is designed primarily for a single-user local workstation. Loopback binding is the secure default. Remote exposure requires an API token and should additionally be protected by host firewall/VPN controls. Tenant IDs provide scheduling/cache namespaces, not hostile-user isolation.

## Identity and shared state

The API token grants access to the local service; it does not establish a distinct authenticated tenant principal. `X-LocalAI-Tenant` and related tenant labels are caller-supplied provenance and scheduling labels. They must not be treated as authorization by themselves. Callers sharing one Hub instance are inside the same trusted-local boundary.

Workspace memos are intentionally shared by canonical workspace and memo key. Reads and searches ignore the tenant label, and a later write to the same workspace/key replaces the earlier value when no expected version is supplied; the stored tenant records who supplied the current value. A memo writer may supply the per-key generation it read to reject a stale overwrite. Deletion retains and advances that generation to prevent stale delete-and-recreate writes. A tenant-filtered delete selects a matching memo but does not authenticate the caller. Agent leases live in shared local coordination state. Tenant labels influence lease conflict and owner checks, but they are caller-supplied and are not proof of identity; another caller able to choose a label can impersonate it.

RAG can partition index rows by the supplied tenant label, and its search cache uses the index revision. Generation caches key request and context content, not an authenticated caller. Treat both as shared local state; label-based partitioning is not private access control.

The Hub does not provide hostile-user isolation for callers that share its state directory. Use a separate Hub instance and state directory per trust domain until an authenticated identity is bound to private memory, lease, evidence, artifact, cache, and deletion operations.

Repository paths, RAG/index databases and exported bundles may contain sensitive source-derived information. Telemetry intentionally excludes prompts, source and model output, but operational logs can still contain paths and error metadata.

The command broker is allowlist/fail-closed and is not a general shell sandbox. The dashboard uses the same policy. External Serena/CodeGraph processes are constrained by project roots, timeouts, bounded sessions and process-tree termination.

Report vulnerabilities according to `SECURITY.md`.
