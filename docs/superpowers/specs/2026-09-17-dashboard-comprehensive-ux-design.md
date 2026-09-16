# Local AI Hub Dashboard UX Design

## Goal

Turn the dashboard into an operational console that states current risk, shows the next useful action, and keeps diagnostic detail available without making it the default view.

## Scope

The change covers Overview, Queue & requests, Agent OS, Projects, Commands, Models & RAG, Reliability & Logs, Configuration, Bundles, Live events, trace details, and the Controls menu. It keeps the existing HTTP surface and stored data formats compatible.

## Information Architecture

Overview becomes the primary operational summary. It shows one derived health state (`healthy`, `attention`, or `degraded`), its evidence, freshness, and a link to the relevant detail view. Secondary metrics remain available but no longer compete with active failures.

Queue owns HTTP request history and trace inspection. Agent OS owns durable task contracts, memories, incidents, and task-run inspection. A trace record without captured agent data states that explicitly and does not expose empty prompt or output panels as if data were missing accidentally.

Projects, Bundles, and RAG use a stable repository identity: display name, canonical root, and short identifier. Views group related worktrees and use filters before long raw lists.

## Shared UI Components

Dashboard helpers provide consistent status badges, empty/loading/error states, alert summaries, scoped action dialogs, repository labels, and redacted diagnostic text. Every action has a text label or accessible label; icon-only destructive actions are removed.

Operational data shows a collection timestamp and a stale/loading state so independently refreshed sections cannot look contradictory. Terminology is normalized: `running`, `queued`, `ready`, `failed`, and `completed` each have one defined meaning.

## Safety and Privacy

Default tables redact local roots, executable paths, command arguments, tokens, and retained payload details. Trace detail offers an explicit reveal control only when the operator needs the data. Controls, project cleanup, cache purge, service restart/stop, export/import, and configuration save show scope and effect before confirmation.

## Section Changes

- Overview: alert-first summary, compact supporting metrics, meaningful graphs with labels and empty states.
- Queue: clear active/history separation, trace availability indicator, actionable empty trace details.
- Agent OS: task-only run history; incidents grouped by fingerprint with recurrence and remediation state.
- Projects: grouped repository/worktree rows, readable progress, text actions, filter for non-ready work.
- Models & RAG: searchable workspace list with owner/path/state; arena describes inputs and compares returned dimensions.
- Reliability: aggregate restart/failure trends, severity, source, and link to affected request or incident.
- Configuration and Controls: grouped safe/operational/destructive actions with impact text and confirmation.
- Bundles: canonical repository labels, one row per identity, readiness/size/content before export.
- Live events: severity and source filters, pause status, event-to-trace navigation.

## Error Handling

Every asynchronous load renders a bounded loading state, then either usable data, a concise empty state, or an error with retry. A failed secondary fetch cannot replace previously valid primary data with zeroes.

## Testing

Add regression tests for health projection, freshness and stale handling, redaction, trace availability, repository deduplication, action metadata, and rendering contracts. Preserve existing dashboard API and browser tests. Verify the full test suite and manually inspect the refreshed dashboard in Chrome.
