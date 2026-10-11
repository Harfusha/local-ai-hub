# Trace Inspector Full Payload Display Design

**Goal:** Trace Inspector retains and pages complete opt-in local payloads while redacting credentials and avoiding content truncation.

## Scope

Keep complete endpoint input, output, paths, and events while detailed traces are enabled, except secret values. Redact credential-shaped fields and inline bearer/token/secret assignments before trace content is stored. Preserve surrounding prompt and output text. Enforce per-event, per-session, event-count, database-size, and retention bounds by evicting whole traces. Dashboard response pages may be bounded, provided callers can retrieve every stored character through the content-page API.

The phrase “all” means exact captured content for each retained trace. A trace that exceeds a configured per-event or per-session bound is removed as a whole; no partial trace is presented as complete. Database size and age limits also remove whole traces.

## Architecture

`DebugTraceStore` remains the authoritative storage boundary. It stores credential-scrubbed serialized payloads in chunked content tables. The dashboard may use bounded previews in list/detail responses, then retrieve full values page by page. Secret filtering happens before storage across requests, effective payloads, events, streamed output, responses, and errors. It must not replace or truncate ordinary human text.

The dashboard keeps configured count and retention controls. If one event or one session exceeds its configured storage cap, delete that entire trace, including metadata and events. Never create a truncated replacement payload or prune individual events.

## Acceptance criteria

1. A nested retained payload deeper than four levels renders its nested value, not `<payload budget truncated>`.
2. A retained payload larger than the former 24 KiB presentation budget renders without the synthetic marker.
3. Secret-shaped keys, authorization headers, bearer credentials, and inline secret assignments are redacted in retained trace content; ordinary input, output, and paths remain readable.
4. An event, session, or event-count cap removes the complete trace; no payload is truncated and no event is individually pruned.
5. Full content pages reconstruct exact multi-chunk Unicode event and session data.
6. No unrelated dirty worktree changes are modified.
