# Security model

Local AI Hub is designed primarily for a single-user local workstation. Loopback binding is the secure default. Remote exposure requires an API token and should additionally be protected by host firewall/VPN controls. Tenant IDs provide scheduling/cache namespaces, not hostile-user isolation.

Repository paths, RAG/index databases and exported bundles may contain sensitive source-derived information. Telemetry intentionally excludes prompts, source and model output, but operational logs can still contain paths and error metadata.

The command broker is allowlist/fail-closed and is not a general shell sandbox. The dashboard uses the same policy. External Serena/CodeGraph processes are constrained by project roots, timeouts, bounded sessions and process-tree termination.

Report vulnerabilities according to `SECURITY.md`.
