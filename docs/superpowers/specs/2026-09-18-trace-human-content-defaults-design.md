# Trace Human Content Defaults Design

## Goal

Make every trace inspector presentation show human-relevant request and result content immediately. Keep technical metadata available behind expandable disclosures. Human output must remain complete rather than being hidden or shortened because it is long.

## Current behavior

`tracePresentationColumns()` renders both request and result sections through `tracePresentationGroup()`. The helper emits closed `<details>` elements for both groups, so command stdout/stderr, review findings, repository results, async results, responses, and similar content require an extra click. `Technical details` is a separate disclosure and is correctly optional.

## Design

- Primary request/result groups open by default when they contain content.
- The result group is human-first: command output, review findings/recommendations, repository result, retrieval answer/results, async result/error, response/output, model output, and agent-loop final output appear without opening `Technical details`.
- Human output is not shortened. Human-facing text and captured output render in full after sanitization and escaping; diagnostic payloads may keep their existing bounds.
- Technical metadata remains expandable: raw JSON, universal summary, event timeline, trace tabs, redaction controls, model context, internal identifiers, and other diagnostic-only fields stay outside the primary human presentation.
- Request groups use the same open-by-default rule when they contain human-relevant request/context content. Empty groups remain omitted.
- Existing user state is preserved during live refresh: if a primary disclosure was manually closed or opened, rerendering should retain that state just as the technical disclosure does.

## Presentation coverage

The audit covers `agent_loop`, `model_chat`, `command`, `review`, `repo_intelligence`, `rag_search`, `async_job`, `request_response`, and generic input/output fallback. Specialized layouts that do not use request/result groups must still expose their human answer/result directly and keep only diagnostic subdetails collapsed.

## Testing

- Add source-level assertions that primary request/result groups default open while `traceTechnicalDetails` remains closed.
- Add JavaScript fixture assertions for each presentation kind, checking human output is present before technical disclosure.
- Add a rerender fixture proving primary disclosure state survives live updates.
- Preserve existing escaping, redaction, empty-value, raw JSON, and technical disclosure tests.

## Scope

Modify the trace presentation rendering and its dashboard tests only. No API, storage, telemetry, or trace data-model changes.
