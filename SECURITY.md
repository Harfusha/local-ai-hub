# Security policy

## Supported version

Security fixes target the current 1.x release.

## Reporting

Do not publish suspected vulnerabilities, secrets, or private repository content in a public issue. Use the repository owner's private security-reporting channel when one is configured on the hosting platform.

## Deployment guidance

- Keep the Hub bound to `127.0.0.1`; remote peers and non-loopback binds are rejected.
- The single-owner loopback service has no Hub API token. Protect the OS account and machine.
- Preserve command authorization, capability policy, root confinement, approvals, leases, rate limits, and audit records.
- Review `[commands]` before enabling mutating or unknown commands.
- Serena and Ollama are Hub-managed local subprocesses/services with access to repositories you point them at; apply normal local-machine trust controls. CodeGraphContext is standalone external CLI/MCP tooling and follows its own process controls.
- Telemetry is designed to exclude prompts/source/model output, but repository indexes and RAG state contain derived local code data and should be protected like source code.

## Identity and shared coordination

The supported trust boundary is a trusted local OS account on one machine. The Hub accepts loopback peers only and does not authenticate them with API tokens. Retired tenant headers and selectors are rejected; they cannot establish caller identity or authority.

Workspace memos are intentionally shared by workspace and key. A later write replaces an earlier value, and reads report scope: "workspace-shared" plus the latest writer label. A delete with a different label does not remove that row, but the label remains metadata rather than proof of identity. Repository memory IDs require the matching repository root. Global memory becomes shared only after an explicit approval marker; the memory store records that marker but cannot authenticate the human approver.

Leases are shared coordination records. Conflicts expose the recorded tenant label, lease ID, and held path so agents can coordinate. Labels such as admin, system, http-default, or * do not grant privileged release or renewal rights. Tenant labels still do not authenticate ordinary callers, so this behavior assumes the trusted-local deployment boundary.

Artifact lookup through HTTP uses the request tenant label as a namespace filter. Direct in-process calls may use the store's unscoped access, which is also trusted-local behavior. Active artifact rows store a hash of the tenant label. The one-time tenant migration writes a verified pre-migration database backup beside the database; that backup can contain the original labels and binary payloads, so protect it like the local state database.

Any future private multi-tenant scope must derive identity from an authenticated principal, not a request label. Include that verified identity in primary and cache keys and in every SQL read, write, and delete.
