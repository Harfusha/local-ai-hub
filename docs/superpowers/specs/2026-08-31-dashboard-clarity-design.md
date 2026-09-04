# Dashboard Clarity Design

**Goal:** Make the Local AI Hub dashboard readable for daily operations while preserving detailed diagnostics behind project rows and specialist tabs.

## Approved direction

Use an operations-first layout. The overview keeps only the most actionable health, queue, preprocessing, latency, reliability, cache, and system signals. Projects becomes a compact, filterable table with one row per project; the existing detail modal remains the secondary diagnostic view.

## Changes

- Move maintenance, authentication, pause, restart, and stop actions into a compact Controls menu.
- Remove the repeated 13-phase legend and redundant overview cards.
- Combine CPU, GPU, RAM, and VRAM into one System card.
- Add project search, status filter, and priority sort.
- Show project name, state/activity, phase/progress, index readiness, and actions in the compact table.
- Keep full paths, detailed phase stepper, counters, errors, and checkpoint age in the project detail modal.
- Preserve the existing API endpoints, project state semantics, polling guard, and 3-project preprocessing limit.

## Acceptance criteria

- A narrow dashboard view exposes the active state and project filters without horizontal scrolling caused by the project table.
- A user can distinguish Running, Waiting, Error, Paused, and Ready projects from one row.
- Detailed project diagnostics remain available by clicking a project row.
- Existing dashboard JavaScript passes syntax validation and the full Python test suite.
