# Trace output, capture and resilience

## Goal

Make local model traces truthful and useful: show the final answer by default, keep thinking and technical payloads expandable, capture repository/review inputs and results, and remove premature failures caused by overly tight token, timeout and retry limits.

## Design

The Ollama runtime will collect structured `thinking` separately from final `response`/chat content. It will emit non-empty final-output and thinking events through distinct observer callbacks, while retaining the raw response metadata. The service layer will return an explicit empty-final-response status when the model finishes without answer text, instead of reporting a misleading successful answer. Dashboard rendering will show final text first, with collapsible thinking and technical detail panels.

Repository and review handlers will attach bounded request, context/diff and result projections to the debug trace at the API boundary. Missing values will remain distinguishable from redaction. Secret filtering will use explicit sensitive-key matching and preserve accounting fields such as `*_tokens`.

Default model output/context ceilings, foreground request deadlines and scheduler waits will be increased within the existing hard safety maxima. Retries will remain bounded, but a model request will receive its full timeout budget rather than losing it to an aggressive retry delay. Existing background cancellation and repetition-loop protections remain active.

## Acceptance criteria

- Final model response is visible immediately in the trace inspector.
- Thinking is stored separately and expandable; it does not replace final response text.
- Empty output deltas are not rendered as output events.
- Repo/review request, context/diff and result fields are captured when supplied.
- Real secrets remain redacted; token accounting metrics are visible.
- Default model operations have sufficient token and time headroom and bounded retry behavior.
- Regression tests cover each behavior and existing tests remain green.
