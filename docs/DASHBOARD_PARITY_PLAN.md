# Dashboard Parity & Migration Plan (HUB-059, HUB-093–102)

## 1. Overview & Routing Strategy

Local AI Hub provides monitoring, operational visibility, and coordination through its HTTP server. To modernize the interface without regressing critical operator workflows, the dashboard architecture follows a three-route migration strategy:

| Route | Target | Purpose | Status |
|---|---|---|---|
| `/dashboard` | Legacy HTML (`_dashboard_html_with_trace_notice`) | Default operational dashboard. Guaranteed backward compatibility. | Active Default |
| `/dashboard/legacy` | Legacy HTML (`_dashboard_html_with_trace_notice`) | Explicit permanent alias for operators and automation scripts. | Stable Alias |
| `/dashboard/next` | 7-Section Static Shell (`ui_static/index.html`) | Modern, accessible, CSP-strict dashboard preview. | Preview Shell |

### Parity Gate Rule
`/dashboard` remains pinned to the legacy UI until **all 7 sections** in the new shell achieve operational parity with the 11 legacy tabs, pass strict keyboard/accessibility validation, and receive test coverage for failure modes and loading states. When the parity gate passes, `/dashboard` will serve the modern shell, `/dashboard/next` will remain as a compatibility alias, and `/dashboard/legacy` will remain permanently available for legacy deep-links.

---

## 2. Legacy Surface Inventory (11 Pages)

The legacy dashboard (`src/local_ai_hub/dashboard.py`) exposes 11 functional tabs:

1. **`overview` (Overview)**: Real-time service status, active mode, live request counters, memory records summary.
2. **`work` (Requests)**: Work order submission, bounded execution status, active lease inspection.
3. **`agentos` (Tasks)**: Task contracts, lifecycle states, milestones, verification receipts, event logs.
4. **`coordination` (Coordination)**: Worktree management, blackboards, pubsub channels, swarm coordination.
5. **`projects` (Projects)**: Repository registration, preprocessing status, FTS/AST index state, reindexing, unregistration.
6. **`commands` (Commands)**: Agent host readiness (Codex, Antigravity, Cursor), CLI tool execution, command history.
7. **`performance` (Models & search)**: Installed model inventory, GPU/VRAM statistics, CPU/GPU admission, search benchmark trigger.
8. **`reliability` (Service health)**: Subsystem readiness breakdown, detailed trace opt-in/out, error code logs.
9. **`config` (Settings)**: Redacted TOML configuration, operational mode switcher, live log tail.
10. **`bundles` (Transfers)**: Project bundle zip export/import, offline diagnostic package export.
11. **`events` (Activity)**: Historical telemetry timeline, structured event pagination, audit tail.

---

## 3. Mapping Matrix to the 7-Section Shell

| Legacy Surface | Target Shell Section | Target View Element | Classification | Status & Migration Notes |
|---|---|---|---|---|
| `overview` | `overview` | `#overview-cards`, `#checked-at` | `implemented native` / `readonly` | Real-time `/ready` checks with visibility-aware polling, degraded dependency detection, snapshot staleness warnings. |
| `projects` | `projects` | `#projects-view`, `#project-form` | `implemented native` / `unsafe` | Root path validation, `/api/preprocess/status`, reindex, safe unregister (`purge_data: false`). |
| `bundles` | `projects` | `#projects-view` (transfers) | `linked legacy` | Bundle import/export currently links to `/dashboard/legacy#bundles`. |
| `commands` | `agents` | `#agents-view` | `implemented native` / `readonly` | Agent host detection (Antigravity, Codex) via `/api/agent/hosts`, CLI path, MCP config path, skills state. |
| `work` | `tasks` | `#tasks-view` | `implemented native` / `readonly` | Work order inspection, lease tracking, stored evidence display. |
| `agentos` | `tasks` | `#tasks-view`, `#task-list` | `implemented native` / `readonly` | Task contract list, stored JSON inspection via `<details>`, worktree listing. |
| `coordination` | `tasks` | `#tasks-view`, `#worktree-response` | `implemented native` / `readonly` | Root-scoped worktree inspection, lease listing. Mutations link to `/dashboard/legacy#coordination`. |
| `performance` | `models` | `#models-view`, `#model-list` | `implemented native` / `readonly` | Model inventory via `/api/models`, owner disclosure, explicit disclaimer regarding runtime VRAM/routing. |
| `reliability` | `diagnostics` | `#diagnostics-view` | `implemented native` / `readonly` | Aggregate telemetry via `/api/telemetry/endpoint-stats`, histogram estimates disclosure. |
| `events` | `diagnostics` | `#telemetry-timeline` | `implemented native` / `readonly` | Paged telemetry timeline via `/api/telemetry/timeline`, cursor-based older events pagination. |
| `config` | `settings` | `#settings-view` | `implemented native` / `readonly` | Redacted config snapshot via `/api/config`. Editing/restarting safely deferred to CLI/legacy. |

---

## 4. Capability Classification Legend

- **`implemented native`**: Action or view is completely handled within `ui_static/app.js` using fetch to native REST endpoints with explicit loading and error states.
- **`linked legacy`**: View or action provides an explicit, labeled link to `/dashboard/legacy#<tab>` so no user capability is lost.
- **`readonly`**: Non-mutating observation endpoint (e.g. status, model list, task view).
- **`unsafe`**: Mutating action that alters disk state or deletes indexes (requires confirmation dialog and explicit parameter guards).
- **`missing`**: Capability not yet exposed; tracked in backlog for subsequent releases.

---

## 5. Security & Accessibility Verification

1. **Content Security Policy (CSP)**:
   - `style-src 'self'`
   - `script-src 'self'`
   - Strict disallow of `unsafe-inline`, `eval`, or external CDNs.
   - Zero `innerHTML` usage in JavaScript; all DOM construction uses `textContent` and `createElement`.
2. **Keyboard Navigation & ARIA**:
   - Skip link (`<a class="skip-link" href="#main-content">Skip to content</a>`).
   - Accessible navigation toggle with `aria-expanded` and `Escape` key close.
   - Screen-reader live regions (`role="status" aria-live="polite"`).
   - High contrast WCAG AA compliant color palette.
   - Responsive breakpoints (max-width 900px, 680px) and `@media (prefers-reduced-motion: reduce)`.
3. **Truthful Host Reporting (HUB-093)**:
   - Never infers host readiness from `capabilities.commands`.
   - Distinct host cards for Codex CLI and Antigravity IDE/CLI.
   - Reports `not_installed` when CLI binary is missing; never triggers automatic downloads.
4. **Live Health Polling (HUB-094)**:
   - Periodic `/ready` polling with `AbortController` and 5s timeout.
   - Visibility-aware: throttles to 30s when backgrounded, immediate refresh on window focus.
   - Exponential backoff on consecutive transport failures.
