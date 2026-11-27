# PR #10 Native Desktop Cutover — Design Specification

**Status:** Active user-approved scope, 2026-11-27  
**Source:** User-provided “GOAL: Complete Local AI Hub PR #10, native Rust desktop application and full dashboard replacement”, sections 1–35.  
**Repository:** https://github.com/Harfusha/local-ai-hub  
**Pull request:** https://github.com/Harfusha/local-ai-hub/pull/10  
**Branch:** `feat/native-desktop-hub` → `master`

## Goal

Finish PR #10 as a production-ready native Rust desktop application and complete replacement for the old web dashboard. Work includes current-master synchronization, all supported operator workflows, security and reliability, measured performance, supported platforms, installer/updater, documentation, full validation, independent audit, PR update, merge and post-merge verification. The complete original document is the exhaustive requirement source; this spec preserves its scope.

## Binding compatibility decision

The user's latest instruction overrides any conflicting text in the original goal or existing code/docs:

- No backward compatibility and no legacy runtime behavior.
- Only allowed exception: one-time migration executed as part of updating an existing installation.
- The updater may detect and migrate old dashboard-era configuration/state exactly once, safely and idempotently. After success, remove obsolete state where safe and record a durable completion marker. A failed/incomplete migration must be recoverable without enabling an old runtime path.
- Do not retain a dashboard CLI alias, old UI HTTP routes, compatibility shims, fallback web UI, duplicate frontend, legacy setting semantics, or runtime branches solely for old callers/data. Remove obsolete routes and entrypoints.
- Keep currently supported canonical Hub HTTP, MCP, and CLI operations where required by the product. This is active functionality, not a legacy alias or compatibility layer. Update callers and documentation to canonical interfaces.
- Do not delete data or introduce a migration beyond the single authorized upgrade migration.

## Architecture and product scope

1. **Architecture:** Standalone native Rust UI using egui/eframe or justified native alternative. No Electron, Chromium, WebView, local web frontend, parallel Python GUI, unnecessary resident helper, or mandatory cloud service. Existing Python Hub owns business logic and canonical data. Desktop uses bounded, typed, allowlisted IPC and shares contracts with CLI/HTTP/MCP. Preserve independent desktop/Hub lifecycles and one source of truth.
2. **Dashboard parity:** Reconstruct relevant historical HTML/TypeScript controls, dynamic workflows, dialogs, tables, charts, filters, keyboard actions, polling/events, loading/error behavior and behavioral tests. Map each to verified native equivalent or justified obsolete removal. No relevant capability may be lost.
3. **CLI parity:** Inventory current subcommands, arguments and errors, including newer commands on master. Provide fit-for-purpose native controls, not a shell console or generic form. Respect canonical authorization.
4. **Operational overview:** Real service/workload, scheduler, jobs, endpoint health, request counts/latency/errors, token/model use, cache/preprocessing/projects, CPU/GPU/VRAM/RAM, bottlenecks, time ranges and drilldowns. Distinguish zero, unavailable, stale, unknown and measurement error.
5. **Requests and execution:** History/active requests, queues, running jobs, recovery journal, work orders and traces; correct filters, sort, paging and links; safe cancellation/continuation/retry; distinguish failed from unknown outcomes and prevent unsafe duplicate mutation.
6. **Agent OS:** Scoped task contracts, lifecycle, criteria, checkpoints, attempts/history/trajectory, receipts, completion gate, blockers, related plan/work orders; completion requires authentic evidence.
7. **Plans and coordination:** Plan lifecycle/editor, task graph/order/dependencies, criteria, blockers, verified/declarative progress, Kanban/briefings, revision fencing, cycle prevention, semaphores, leases and worktrees; respect scope and owner checks, avoid lost updates/upserts.
8. **Memory, incidents, knowledge:** Supported scopes, search/detail/provenance/confidence/quarantine/removal, incidents/root cause/lessons, knowledge audit/migrations/batches/handoffs; Git-first and canonical Hub data only.
9. **Projects/preprocessing:** Registration/config/removal/purge, scoped reindex/pause/resume, progress/backlog/index/embedding/RAG freshness and errors; clear stale UI state on scope changes.
10. **Commands/resources:** Running/blocked command history and reasons, worktrees, file leases, semaphores and supported resource/GPU leases; no privileged generic executor; confirm exact destructive target.
11. **Models/inference/RAG:** Configured/installed/resident models, provider/backend/profile/routing/fallback, statistics/cache/agents/routes/tokens/latency, benchmarks/evals/embeddings/rerank/RAG/Laya/hardware and supported model controls. Separate installed from resident/unknown; expensive operations require explicit user action.
12. **Telemetry/activity:** Trace inspector, content pages, timelines/metrics/links, paging/search, redacted export, explicit sensitive reveal, endpoint/MCP/process/error/circuit/crash analytics; correct event cursor/replay/dedup/reconnect/gap/pause semantics. No sensitive leakage into generic search/log/export.
13. **Vision:** Validate inspected image bytes, size/dimensions/integrity and exact-byte consent; prevent TOCTOU replacement; show route/model/result/history/trace; no implicit upload.
14. **Configuration:** Typed, documented and validated forms for supported groups; effective/default/source values, changed-field saves, reset, restart requirements, concurrency fencing and secret protection; shared canonical configuration.
15. **Lifecycle:** Desktop and Hub start/stop/restart independently; safe repeat/reconnect/shutdown, owner/PID verification, permissions, port/config errors, supervisor/service managers, multiple installs/instances; closing desktop never shuts down Hub implicitly.
16. **Transfers/diagnostics:** Canonical import/export and encrypted diagnostic flows with integrity, bounded streaming, progress/cancel, password reveal, overwrite and archive/path/symlink safety.
17. **Client integrations:** Installed-client detection/status, preview and managed artifacts/instructions; staged review/apply/restore applies exact reviewed bytes with revision/hash fencing and never reruns inference.
18. **UX/accessibility:** Coherent native navigation, specialized views, keyboard and screen-reader support as toolkit/OS allow, file dialogs, confirmations, errors/empty/loading states, HiDPI and window-size behavior, large-list responsiveness and safe context retention. Generic JSON is supplementary.
19. **Performance:** Measure startup/first window/readiness, idle/peak CPU/RAM/GPU, IPC, data volume, rendering, large lists, polling and long-run behavior across offline/online/idle/minimized/active states. Source targets: first window under 500 ms, usable under 1 s with Hub, idle CPU under 1% of one core, idle RSS about 120 MiB; report platform/method and explain material misses.
20. **Security/reliability:** Audit Rust, bridge, HTTP, MCP, CLI, installer/updater and packaging: allowlists, validation, injection/path/TOCTOU/scope/auth/secrets/redaction/resource limits/timeouts/deadlocks/process ownership/concurrency/receipts/cancellation/unknown outcomes/shutdown/update integrity/supply chain. Add regressions for confirmed defects.
21. **Web removal:** Remove old dashboard HTML/CSS/TS/JS/build/dependencies/assets/routes/lifecycle/config/helpers/docs/fixtures/workarounds when not shared canonical backend. No blind keyword deletion. No web fallback.
22. **Platforms:** Verify Windows x64, Linux x64, macOS Intel and Apple Silicon. Investigate ARM64 extras without claiming support absent runtime proof. Verify native window, rendering, input, files, config, IPC/auth, lifecycle, install/update/uninstall on real platform runners.
23. **Installer/distribution:** First install, one-time old-install migration, desktop/Hub independent updates, platform/architecture, versioned install, compatibility/integrity/checksums, atomic update/rollback/recovery, running-app/headless behavior, uninstall/OS integration. License inventory/notices/Cargo.lock/SBOM and dependency review. Real signing/notarization automation and gates; never fabricate credentials or receipts.
24. **Maintainability:** Review/split oversized Rust and Python bridge files by responsibility; typed contracts, consistent errors/mutations/confirmations, testable view models, remove dead code and needless dependencies without speculative abstractions.
25. **Validation:** Rust format/Clippy/locked build/tests, native UI/runtime, bridge/IPC/HTTP/MCP/CLI/security/E2E, installer/migration/rollback, performance/long-run/scope, full supported Python suite (fresh `pytest --run-all` or complete CI shards), coverage/contract/source-goldset/entrypoint/release/security/selftest. Preserve quality thresholds; cancelled/skipped/superseded jobs are not pass evidence. Isolate tests from live user data.
26. **Docs/parity:** Update README, desktop/parity, install/update/platform/architecture/config/CLI/troubleshooting/security/contributing/testing/release docs. Parity register links each original relevant workflow to implementation and actual verification; no unsupported completion claims.
27. **Final audit/delivery:** Audit the full diff against current master, contracts, all requirements, parity, CLI, security/performance/UX/platforms/tests/CI/installer/docs/plan; fix and reverify blockers. Commit/push on the existing feature branch, keep PR #10 non-draft only when gates qualify, respect branch protection, merge, verify merged state/master/post-merge CI, update plan with authentic evidence, preserve/clean work safely. Report actual results, commits, PR, merge SHA, platform measurements, checks and external blockers.

## Acceptance

- Every source section 1–35 and every relevant historic dashboard/CLI workflow is represented in the authoritative Hub plan/parity register with current status and evidence.
- No backward-compatible/legacy runtime path remains; only the explicitly authorized one-time updater migration remains.
- Native desktop is the only dashboard UI and uses canonical Hub behavior/data.
- Required feature, security, performance, platform, installer, test, CI, documentation and release criteria pass or have exact, genuinely external blockers; no implementation gap is hidden as obsolete.
- PR #10 is actually merged to master and current post-merge state is verified.

Any reduction or exception requires direct user instruction. External credentials/platform availability may block only corresponding signing/runtime evidence; finish independent work without inventing evidence.
