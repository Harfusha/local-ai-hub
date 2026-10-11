# Local-only Hub control boundary

**Status:** Normative

## Goal

Local AI Hub has no remote-use or remote-control mode. Keep the local dashboard and stdio MCP adapter working through loopback HTTP.

## Requirements

- The daemon binds only to IPv4 loopback `127.0.0.1`.
- The HTTP server enforces loopback at the socket-bind boundary, including direct construction outside `serve()`.
- `HubClient`, supervisor probes, and in-process HTTP simulation always target `127.0.0.1`.
- Remove `server.client_host` and `security.allow_remote`; reject either key when supplied, including `allow_remote = false`.
- Remove configurable external `security.allowed_hosts` and `security.allowed_origins`; reject non-empty overrides.
- Host and origin checks accept only built-in local origins and the configured loopback bind.
- Local dashboard and local stdio MCP use remain supported. No remote Hub endpoint or credential turns remote access on.
- Keep the Browser Bridge for local browser control only; it must not expose or enable remote Hub access.
- Same-machine Browser Bridge remains supported; it does not allow clients to target a remote Hub.

## Acceptance

- Config rejects wildcard, IPv6, hostname, or other non-`127.0.0.1` binds.
- Direct HTTP server construction rejects non-loopback addresses before binding a listening socket.
- Config rejects removed remote options and remote host/origin overrides.
- Client, supervisor, and in-process transport have no configurable Hub host.
- Existing local dashboard/MCP transport contracts remain covered by focused tests.
- Architecture, install, update, and troubleshooting docs state the same local-only rule.
