# T03 design: MCP contracts and Hub auto-start

**Status:** awaiting user review  
**Scope:** T03-owned contract/validation work; retain the current eight-tool MCP surface.

## Context

The MCP server constructs an HTTP `HubClient` with auto-start enabled. The client already has a bounded readiness wait and uses a cross-process start lock to avoid duplicate launches. The daemon-off path therefore already targets the HTTP service contract; replacing it with an in-process façade would introduce a second request path and duplicate service wiring.

There is a contract mismatch on the registration route: `http_server.py` calls `RecoveryJournal.begin` and `wait_for` with identity and fingerprint data, while the T03 `resilience.py` API does not accept those arguments. As written, a registered POST can become a 503. The user authorized a narrow API port into T03.

## Decisions

1. **Keep the HTTP transport and Hub-owned auto-start.** On a daemon-off request, MCP asks its existing `HubClient` to start the Hub and waits for readiness within the request's remaining deadline. Concurrent callers share the existing start lock. The HTTP route and public MCP schemas remain the single source of behavior.
2. **Keep eight public MCP tools.** Action-specific schemas live behind the existing tools. Split tools only if later evidence shows a material usability or token benefit.
3. **Make action schemas describe runtime behavior.** Each action has a bounded argument schema; generated MCP input schemas expose the same action set and constraints. Validate arguments before HTTP dispatch so malformed calls produce a client-visible validation error rather than a Hub 503. Keep conditional receipt evidence requirements represented in JSON Schema.
4. **Port only the missing RecoveryJournal API.** Add the identity/fingerprint parameters and matching replay/wait behavior required by the registered route. Do not add deprecated aliases or migration shims. Preserve the route's idempotency semantics and avoid changing unrelated resilience behavior.
5. **Bound startup and clean up only owned children.** Startup/readiness consumes the caller's remaining deadline. If that wait expires, terminate and reap only the child started by that startup attempt; never stop a pre-existing service or a process marked as externally managed. Handle concurrent startup so one caller's timeout cannot kill a child another caller is relying on. Use the repository's process-tree helper on Windows.

## Alternatives

| Option | Assessment |
| --- | --- |
| Hub-owned HTTP auto-start | Reuses the existing client, readiness check, start lock, and HTTP dispatch. Preserves one service path and the eight-tool surface. Recommended. |
| In-process MCP façade | Could avoid a daemon, but would need to reuse service construction without starting a second divergent path; it also bypasses the HTTP route contracts being repaired. Not selected. |

## Ownership and boundaries

- T03 may change its operation contract registry, MCP schema/validation code, T03-owned resilience API, and their owned tests.
- `client.py` and `tests/test_client_transport.py` are T04-owned. User approved a narrow release for startup timeout cleanup: only terminate and reap the child process created by the current `ensure_server` attempt after readiness times out. Do not change request dispatch, connection pooling, retry behavior, or other client transport code.
- `http_server.py` is T07-owned; treat its call shape as the compatibility target and do not edit it in this work.
- Do not modify `/api/context/pack` or unrelated inherited dirty paths.

## Acceptance criteria

- The eight public MCP tools remain present; their action enums and argument schemas match the action-specific runtime contracts.
- Invalid, missing, extra, or out-of-range arguments fail before an HTTP request is sent.
- Conditional receipt requirements validate correctly for both evidence and non-evidence receipts.
- The registration route's existing identity/fingerprint calls are accepted and preserve the expected idempotent wait/replay result.
- With the daemon stopped, an MCP call starts one Hub process and becomes ready within a bounded deadline; concurrent calls do not spawn duplicate children.
- Startup timeout cleanup reaps only a child owned by the timed-out startup attempt; a pre-existing/managed service remains running.
- Focused tests exercise daemon-off startup, simultaneous callers, startup timeout cleanup, and existing-server behavior using controlled fakes so no orphan process is left behind.
- No public HTTP route or MCP tool is added, removed, or renamed.

## Validation and rollout

After this spec is approved, prepare a file-scoped implementation plan. The T04 timeout-cleanup ownership release is approved for the narrow edit above. Run focused contract, route, and client transport tests through the Hub command broker; do not claim runtime daemon behavior from source-only checks. Complete only after the relevant validation receipts and ownership handoff are recorded.

## Explicit non-goals

- No in-process duplicate service façade.
- No change to `/api/context/pack`.
- No expansion of the public MCP tool count.
- No edits to T07 files; T04 edits are limited to the approved startup timeout cleanup and its focused tests.
- No broad refactor of process management or resilience behavior.
