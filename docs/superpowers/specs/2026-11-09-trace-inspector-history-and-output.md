# Trace Inspector History and Output

## Goal

Make retained traces load on direct Inspector links, link request-history rows to their trace records, and capture model output for enabled HTTP traces.

## Design

- Load the trace-summary list whenever Requests, Reliability, or Trace Inspector is active. A direct `#traceInspector` load must fetch summaries before rendering the history list. Keep the existing bounded list request and error handling.
- When an enabled HTTP request creates a trace, attach a `DebugTraceObserver` to that request's trace context. Model services already use the observer to persist model input, output chunks, and thinking events. Reset the observer with the request context at completion.
- Preserve the distinction between model `output` and the HTTP `response` payload. Do not relabel deterministic endpoint responses as generated model text.
- Resolve request-history availability from exact `request_id` matches against loaded trace summaries. Keep “unverified” only while the association is genuinely unknown.

## Acceptance Criteria

1. Opening `#traceInspector` directly loads retained trace summaries from `/api/debug-traces`.
2. A request row whose `request_id` matches a retained trace displays “Trace available”.
3. A model response generated during an enabled HTTP request appears in the trace's Output field and `output_delta` timeline.
4. The endpoint's final JSON response remains separately available as Response.
5. Disabled capture remains off by default; no new capture occurs when disabled.

## Non-Goals

- Change telemetry defaults or retention.
- Merge model output and HTTP response into one field.
- Alter existing trace redaction or storage policy.
