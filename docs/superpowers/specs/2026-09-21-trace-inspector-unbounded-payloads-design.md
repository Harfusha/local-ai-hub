# Trace Inspector Full Payload Display Design

**Goal:** Let Trace Inspector show all payload data retained by the trace store without synthetic `<payload budget truncated>` markers.

## Scope

Change the trace-store defaults and the dashboard presentation path. Raise the stored event limit from 64 KiB to 4 MiB and the stored session text limit from 8 MiB to 64 MiB. Remove client-side depth and presentation-budget markers from normal Trace Inspector rendering while preserving sensitive-field redaction, the configured event-count limit, trace retention, and explicit backend storage bounds.

The phrase “all” means all data retained after redaction and storage bounds. Payloads already discarded by an older trace record cannot be reconstructed by the dashboard.

## Architecture

`DebugTraceStore` remains the authoritative storage boundary. Its larger defaults allow complete practical event and text payloads while preventing unbounded disk growth. `dashboard.py` continues to use sanitized trace data, but its primary and technical renderers serialize the complete retained values instead of recursively inserting a truncation marker at depth or character limits.

The dashboard keeps the existing trace-count and retention controls. It must not expose secrets while removing display-only truncation. Existing backend truncation metadata remains available for records captured beyond the configured storage limit.

## Acceptance criteria

1. A nested retained payload deeper than four levels renders its nested value, not `<payload budget truncated>`.
2. A retained payload larger than the former 24 KiB presentation budget renders without the synthetic marker.
3. Sensitive keys remain redacted.
4. Default `max_event_bytes` is 4 MiB and default `max_session_text_bytes` is 64 MiB.
5. Existing Trace Inspector tests and the full Python test suite pass.
6. No unrelated dirty worktree changes are modified.
