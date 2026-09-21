# Trace Inspector custom presentations

## Goal

Make every Trace Inspector request type immediately useful. The first view must answer what ran, what it received, what it produced, whether it succeeded, and what deserves attention. Technical metadata remains available through focused expandable sections instead of hiding the useful result inside one generic disclosure.

## Scope

Update the existing client-side Trace Inspector renderer in `src/local_ai_hub/dashboard.py`, its contract/runtime tests in `tests/test_dashboard_custom_modals.py`, and the dashboard documentation in `docs/DASHBOARD.md`.

Supported presentation kinds:

- `model_chat`
- `agent_loop`
- `command`
- `review`
- `repo_intelligence`
- `rag_search`
- `async_job`
- `request_response`

Trace APIs, polling, SQLite persistence, redaction defaults, tab state, and raw trace fallback remain unchanged.

## Design

### Shared layout contract

Every presentation follows the same hierarchy:

1. Header: human title, lifecycle state, actor/model when meaningful, project label.
2. Primary summary: type-specific request/input, result/output, status, error, and the most useful timing or count.
3. Attention section: failures, warnings, missing capture, truncation, or incomplete/live state.
4. Expandable secondary sections: long content, execution steps, tool details, metadata, correlations, raw JSON, and universal diagnostic views.

Primary sections must not be nested inside `Technical details`. Long values remain bounded in the initial view and expose explicit expand/copy controls. Empty, internal-only, duplicate, and none-like values stay omitted unless they explain missing data or failure.

### `model_chat`

Show prompt/messages and final response first. Show chronological tool calls/results when present. Keep reasoning, model options, request envelope, and execution timeline expandable. Preserve model-input precedence and bounded safe rendering.

### `agent_loop`

Show objective/request, final result, lifecycle, and failure summary first. Show ordered steps and tool outcomes as readable cards. Expand raw tool payloads, correlations, event metadata, and full timeline per step.

### `command`

Show command, arguments, exit state, duration, and success/failure first. Show useful stdout/stderr with bounded previews and copy/expand controls. Keep working directory, paths, retries, criterion, environment-like metadata, and raw payload secondary.

### `review`

Show review target/scope, overall status, severity counts, recommendation, and findings first. Findings remain readable and grouped by severity. Expand diff, context, full finding payloads, and technical review metadata.

### `repo_intelligence`

Show operation, repository/root, query, result summary, changed files or symbols, and errors first. Show answer/context cards before technical evidence. Expand full evidence, callers/graph details, raw result objects, and diagnostic metadata.

### `rag_search`

Show query, answer, result count, and ranked result cards first. Each result exposes title/source/snippet; score, provider, path, and full payload expand per result. Truncation and no-result states are explicit.

### `async_job`

Show job type, lifecycle, current progress/state, queue wait, retries, result, and error first. Expand worker input/output, job identifiers, scheduler correlations, event timeline, and raw payload.

### `request_response`

Show method/path/action, status, duration, request body, response body, and error first. Expand headers, request identifiers, actor/tenant, correlations, retained-byte data, lifecycle timing, and raw JSON.

## Safety and behavior

- Continue using existing sanitize, redaction, escaping, bounded rendering, and truncation helpers.
- Do not expose secrets, headers, tokens, or internal identifiers in primary markup.
- Keep technical disclosures closed by default and preserve explicit open state during polling refreshes.
- Preserve keyboard-accessible native `<details>` controls and responsive single-column layout.
- Unknown or malformed traces use a useful generic request/response fallback, never an empty inspector.

## Testing

Add or update tests to prove, for every kind:

- primary human content appears outside `Technical details`;
- status/result/error and relevant type-specific fields are present;
- technical metadata is expandable rather than required for the first useful answer;
- missing fields, empty values, redaction, truncation, malformed objects, and escaping remain safe;
- model chat and agent loop keep chronological tool/timeline behavior;
- command, review, repository, RAG, async, and request/response fixtures render semantic labels rather than generic JSON;
- the outer technical disclosure remains closed by default and survives incremental refreshes.

Run focused dashboard tests, Python compilation, `git diff --check`, and the full test suite with a bounded timeout.

## Non-goals

- No new trace API or persistence schema.
- No redesign of Queue & requests navigation, trace polling, or Agent OS task views.
- No visual framework or frontend dependency introduction.
- No removal of raw JSON, event timeline, redaction controls, or diagnostic tabs; they move behind appropriate focused disclosures.
