# Trace Inspector request presentations

## Goal

Make Trace Inspector readable by choosing a purpose-built presentation for each request family. The inspector must show the useful payload first, keep diagnostic metadata optional, preserve redaction, and remain compatible with the existing debug-trace API and stored SQLite data.

## Scope

Change the dashboard presentation layer and its tests. Do not change the debug-trace HTTP schema, persistence schema, retention policy, or model execution behavior. Presentation selection derives from existing session fields and ordered events.

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

If a trace matches both `agent_loop` and a more specific action such as review, the agent loop layout keeps the chat view and adds the specific review context card. Selection must never hide recorded input or output.

## Data model

Extend the existing display model with bounded, sanitized presentation data:

- `presentationKind` and a human label.
- `requestEnvelope`: original HTTP/API request metadata.
- `modelInput`: highest-priority `model_request` payload, then `effective_payload`.
- `modelOutput`: retained output or ordered output events.
- `chatTurns`: model input/output pairs grouped by model request and step.
- `toolInteractions`: tool call/result pairs with status and duration.
- `command`: command, arguments, stdout, stderr, exit status, retry metadata.
- `review`: target, diff/context, findings, severity counts, final recommendation.
- `repoOperation`: root/repository label, query, operation, result summary and files/symbols.
- `retrieval`: query, sources, scores, answer and truncation state.
- `lifecycle`: existing queue/run/retry/terminal data.

All values pass through existing bounds and `traceSanitizeValue`. Missing data renders an explicit unavailable state, never an empty-looking fake panel. Raw projection remains bounded and optional.

## Rendering

Add one dispatcher, `renderTracePresentation(model)`, with small renderers per presentation kind. The main trace page renders:

1. compact identity/status header;
2. selected primary presentation;
3. collapsed `Technical details` containing universal summary, timeline, events, raw JSON, and redaction controls.

`model_chat` uses a two-column desktop layout requested by the user: model output on the left, the full model input on the right. On narrow screens it stacks output above input. Long prompt/output content remains scrollable and copyable; message roles and model-step boundaries stay visible.

Specific renderers may add only data relevant to their family. They must not duplicate the entire universal summary. A generic fallback remains available for unknown future request types.

## Detection and error handling

Detection uses normalized action, kind, event types, and recorded fields. It is deterministic and does not call a model. Unknown or malformed payloads fall back to `request_response`; renderer exceptions are isolated so one trace cannot break the dashboard. Existing polling, tab selection, scroll restoration, redaction and incremental events remain unchanged.

## Testing

Add static contract tests for every presentation kind and dynamic JavaScript fixture tests for:

- model input/output precedence and chat turn grouping;
- tool-call pairing;
- command stdout/stderr and exit state;
- review, repository, RAG, async-job and generic fallback layouts;
- missing fields, truncation and redaction;
- responsive primary content and optional technical details.

Run focused dashboard/debug-trace tests, then the full repository suite. Manually inspect one model request, one tool loop, one command, one review/diff request, one repository operation, one RAG query and one async job.

## Compatibility

No backend endpoint or persisted data change. Existing traces without newly expected fields continue through the generic renderer. New presentation fields are derived client-side from already retained bounded data.
