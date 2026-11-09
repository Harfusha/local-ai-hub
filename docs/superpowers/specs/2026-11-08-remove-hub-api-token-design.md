# Remove Hub API Token Authentication

Date: 2026-11-08  
Status: Approved by operator  
Repository: `C:\Users\Adam\.local-ai-hub`

## Intent

Remove Hub API-token authentication. A single-user Local AI Hub should work on its owner PC without configuring, copying, or supplying a Hub API token. This follows the operator's explicit direction to remove API-token authentication across the Hub.

## Goals

- Remove global, supervisor, action-scoped, and OpenCode-profile bearer credentials from Hub HTTP and MCP authentication.
- Remove token configuration and transport surfaces, including `security.api_token`, `security.supervisor_token`, `security.action_tokens`, `security.api_token_permissions`, `LOCAL_AI_HUB_TOKEN`, `X-LocalAI-Token`, and Hub API `Authorization: Bearer` handling.
- Allow local Hub clients on loopback without an API credential.
- Reject non-loopback access. The Hub must bind only to a loopback address; a non-loopback bind configuration must fail at startup with a clear error.
- Reject retired token fields explicitly. Do not add aliases, compatibility shims, or silent token migration.
- Keep endpoint input validation, project-root confinement, command authorization, capability checks, approval gates, writer leases, rate limits, audit events, GPU admission, and process ownership.
- Keep the OpenCode provider bridge's nonce-scoped credential. It authenticates a separate loopback inference endpoint and is not a Hub API credential.
- Update `docs/INSTALL_PROMPT.md` and `docs/UPDATE_PROMPT.md` with the new contract.

## Non-goals

- No remote or multi-user Hub access.
- No removal of command-level authorization, capability policy, project scopes, or task/session identity.
- No model downloads or changes to model routing.
- No changes to CORS allowlists or browser-capture capabilities beyond removing token-header alternatives.
- No automatic migration of existing configuration files.

## Proposed behavior

The Hub treats an HTTP request as owner-local only when its peer address is loopback and host/origin validation succeeds. Non-loopback requests fail closed before route handling, including health, readiness, dashboard, browser, provider lifecycle, and administrative routes. Configured hosts outside loopback reject during startup.

Loopback callers need no Hub credential. Existing route validation and command-level authorization still apply. Request headers cannot grant a remote or privileged identity. Browser integrations continue to require exact configured origins and their existing one-use capture capabilities.

Hub clients stop reading or sending Hub API tokens. OpenCode uses the same tokenless loopback Hub API. Its provider bridge retains its separate nonce-derived bearer credential and existing model, peer, GPU, cleanup, and uncertainty fences.

Configuration containing retired token fields fails with a message naming the field and directing the operator to remove it. The Hub does not rewrite configuration or preserve a runtime fallback.

## Acceptance criteria

1. Config schema and startup reject every retired Hub API token field; no generated client config or child environment carries one.
2. Hub HTTP and MCP clients on loopback work without credentials. No Hub route accepts token headers or bearer credentials as authorization.
3. Every non-loopback request is rejected, and non-loopback listener configuration cannot start.
4. Existing project-root confinement, command authorization, capability checks, approval, writer-lease, rate-limit, and audit tests still pass.
5. OpenCode tokenless integration covers provider start, inference bridge authentication, restricted project workflow, stop, cleanup, and uncertainty handling.
6. Docs, installer/update prompts, defaults, diagnostics, SDK clients, and tests contain no retired Hub API-token contract.
7. Focused Windows tests, static checks, and release checks pass. Live GPU/model evidence remains a separate gate and uses installed models only.

## Risks and boundaries

Removing Hub API tokens means any process running as the same user can call local loopback routes. This matches the single-owner local installation model; it does not authenticate individual local processes. Non-loopback access must remain impossible even when a caller spoofs `Host`, `Origin`, agent, or identity headers.

Existing configurations that define retired token keys will stop at startup until the operator removes those keys. Provider bridge credentials remain scoped to one active local inference session and must never authorize Hub API routes.

## Implementation order

1. Inventory all token-based authorization and configuration surfaces.
2. Add regression tests for tokenless loopback operation, retired-field rejection, non-loopback denial, and preserved route-level controls.
3. Remove Hub API token parsing, generation, storage, docs, and client propagation.
4. Run focused integration and security tests, inspect the full diff, then commit this change atomically.
5. Resume the audit plan only after this contract is verified.
