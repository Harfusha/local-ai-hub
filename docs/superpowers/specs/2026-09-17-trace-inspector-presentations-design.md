# Trace Inspector request presentations

## Goal

Make Trace Inspector readable by choosing a purpose-built presentation for each request family. The inspector must show useful payloads first, keep diagnostic metadata optional, preserve redaction, and remain compatible with the existing debug-trace API and stored SQLite data.

## Scope

Change only the dashboard presentation layer and its tests. Do not change the debug-trace HTTP schema, persistence schema, retention policy, or model execution behavior. Presentation selection derives from existing session fields and ordered events.

## Presentation selection

`tracePresentationKind(model)` returns one stable kind, using the first matching rule:

| Kind | Detection | Primary layout |
| --- | --- | --- |
| `agent_loop` | model chat plus tool calls/results | Chat session with tool cards between model turns |
| `model_chat` | model events or a recorded model payload/output | Chat session: model output left, complete model input right |
| `command` | action `/api/command` or command-shaped payload | Terminal: command, stdout, stderr, exit status, retries |
| `review` | action contains `/review` or `/diff` | Review: request/diff/context left, findings/output right |
| `repo_intelligence` | action is repo/code/git/resolve/test/impact related | Repository operation: query, repository, context, results, changed files |
| `rag_search` | action or payload is RAG/search/query related | Retrieval: query, ranked sources, generated answer |
| `async_job` | session kind `async_job` or scheduler/worker linkage | Lifecycle: queue, attempts, worker input, result/error |
| `request_response` | fallback | Request and response cards with status/timing |

If a trace matches both `agent_loop` and a more specific action such as review, the agent-loop layout keeps the chat view and adds the specific review context card. Selection never hides recorded input or output.

## Human-first default

The default detail is a human summary with technical details collapsed. The top answers what happened, whether it succeeded, and what the useful result was. Empty values (`empty`, `null`, empty lists/objects), internal identifiers, and duplicate metadata are hidden unless needed to explain the trace. Labels use human wording; technical names stay in the optional section.

Raw JSON and the existing universal summary, event timeline, tabs, and redaction controls remain available in a closed `Technical details` disclosure. Long text is bounded in the summary and expandable/copyable where supported.

## Data model

Extend the existing bounded, sanitized display model with:

- `presentationKind` and human label;
- `requestEnvelope`, `modelInput`, `modelOutput`, `chatTurns`;
- `toolInteractions` with status and duration;
- `command` with command, output, exit state, and retries;
- `review` with target, findings, severity counts, and recommendation;
- `repoOperation` with repository label, query, result summary, and files/symbols;
- `retrieval` with query, sources, scores, answer, and truncation state;
- `lifecycle` with queue, run, retry, terminal, result, and error data.

All values pass through existing bounds and `traceSanitizeValue`. Missing data renders a concise unavailable state, not a fake empty panel. Raw projection remains bounded and optional.

## Rendering and data flow

Add one dispatcher, `renderTracePresentation(model)`, with small renderers per presentation kind. `renderTraceDetail` places a compact identity/status header first, the selected human presentation second, and the collapsed technical disclosure third. The existing trace model, API, polling, tab selection, scroll restoration, and incremental events stay unchanged.

`model_chat` uses a two-column desktop layout with model output left and full model input right; narrow screens stack output above input. Specific renderers show only data relevant to their family and never duplicate the entire universal summary. Unknown kinds use a generic human-readable renderer rather than `[object Object]`.

## Detection and error handling

Detection uses normalized action, kind, event types, and recorded fields. It is deterministic and never calls a model. Unknown or malformed payloads fall back to `request_response`; renderer failures are isolated so one trace cannot break the dashboard. Available technical data remains accessible when the primary payload is incomplete.

## Testing

Add static contract tests for every presentation kind and dynamic JavaScript fixture tests for model input/output precedence, chat grouping, tool pairing, command output/exit state, review, repository, RAG, async-job and generic fallback layouts. Cover missing fields, empty/internal/duplicate omission, truncation, redaction, escaping, responsive primary content, closed technical details, existing tabs, and raw JSON fallback.

Run focused dashboard/debug-trace tests, then the full repository suite and release validation. Manually inspect representative model, tool-loop, command, review, repository, RAG, and async-job traces.

## Compatibility

No backend endpoint or persisted data change. Existing traces without newly expected fields continue through the generic renderer. New presentation fields are derived client-side from already retained bounded data.
