# Laya and Provider Integration

## User intent

Laya is an actively used part of Local AI Hub. All providers advertised as supported by the Hub must have a complete, truthful integration through the surfaces each provider actually supports: MCP, skills/instructions, plugins, hooks, setup, and runtime handshake. Laya runs only for active typed decisions; background evaluation is not run.

## Product behavior

- The Hub owns one local Laya decision service shared by all providers. Do not create one model daemon or duplicate Laya state per provider.
- Active Laya decisions participate wherever the Hub has a registered typed decision that can materially change an ordinary request: model-tier selection, retrieval strategy, context budget/source, and next-step guidance. Use the shared runtime across all fitting Hub entrypoints; no arbitrary per-request decision-count limit applies.
- Repository `solve` and direct repository `delegate` use current verified evidence for model-route advice. The role passed to model availability checks must be the actual Hub role (`fast_code`, `heavy_code`, `reasoning`, or `general`), not the request classifier's task type. Apply only digest-verified distinct models; preserve explicit caller model selection, prevent high-risk fast downgrades, and do not apply `generic` to code/reasoning requests.
- Repository solve may return typed delegation posture and subagent-budget recommendations as metadata when a low-risk pipeline decision has evidence. These recommendations never change the deterministic plan or start a worker/agent by themselves.
- Every decision remains typed, bounded, attributable to the provider and any available verified session, and scoped to the authorized repository/request. If a real Agent OS task exists, bind to its verified task and session. Never require or fabricate a task ID for ordinary requests.
- Request-scoped decisions require a resolved authorized repository, current evidence IDs verified against that repository, a deterministic Hub baseline, and the active runtime. The decision ID identifies the request decision; it is not a task or session identity. If the host provides no verified session ID, persist it as unknown/null.
- A task ID is optional for ordinary request decisions. Accept a task ID only when the Hub verifies the real task under the authorized repository; derive session identity from that task. Do not require a task for repository-scoped decisions or invent either identity.
- `evaluate_context_source` accepts repository-scoped requests without task/session fields. Evidence and source arrays remain aligned and provenance-checked. Taskless memory must resolve to repository-scoped memory; task/session memory remains available only with a verified task. Taskless runtime output is telemetry only, never a supervised candidate.
- Laya never grants host permissions, bypasses user approval, executes tools, changes task/receipt state, approves completion, or performs destructive operations. Those remain with the deterministic Hub and host.
- Task lifecycle, completion, and watchdog decisions require a real verified Agent OS task. Subagent-budget advice is request-scoped metadata and never starts agents or changes deterministic delegation gates.
- Inference stays local. Capture only data needed to reproduce an eligible decision; redact secrets, bound payloads, and preserve provenance. Human labels remain distinct from model reviews. Request-only decisions may produce runtime telemetry but are not training candidates without an authentic task/outcome link. Integration does not authorize model training, benchmark jobs, model downloads, publication, or rollout by itself.
- Do not route exact search, deterministic facts, administrative/status calls, mutations, permission checks, high-impact operations, or requests without verified evidence through Laya. Preserve their deterministic authority and host approval gates.

## Provider contract

- Treat the enabled provider list in Hub configuration as the inventory source; currently inspect Codex, Antigravity/Gemini, Claude, Cursor, Windsurf, VS Code/Copilot, OpenCode, and extra MCP paths.
- MCP is the shared live capability surface. Each provider's installed skill/instructions must teach the same current Hub route and respect the live tool schema.
- Use native plugins/hooks only where the provider supports them. A hook may provide authenticated, bounded lifecycle context; it must not pretend to know prompts, permissions, or session identity that the host did not provide and verify.
- Setup must preserve unrelated host configuration, expose preview/apply/rollback where it writes hooks, report partial installation, and never auto-trust a host hook.
- Provider status distinguishes configured, installed, enabled, trusted, connected, and runtime-verified. Presence of a manifest or MCP entry is not proof of a working provider.
- Unsupported or unavailable surfaces are reported per provider with their fallback path. Do not claim universal hook parity when an API does not provide it.

## Acceptance criteria

1. A source-backed matrix names every enabled provider, supported MCP/skill/plugin/hook surfaces, installation path, trust requirements, verification method, and limitations.
2. Laya handles applicable decisions through active typed advisories. Evaluation uses only actual outcomes from these active calls; no passive comparison path exists.
3. Laya suggestions affect eligible routing decisions; failure/abstention uses deterministic behavior and records an honest status.
4. Applicable low-risk decisions run for repository-scoped requests with verified current evidence even when no Agent OS task exists. Request scope never manufactures task/session identity or task lifecycle state.
5. Task lifecycle, completion, watchdog, task-scoped memory, and supervised candidate capture remain attached to a verified real task and session. Request-scoped subagent-budget advice needs no task and cannot launch agents. Request-only decisions produce telemetry without task-linked candidates.
6. All appropriate repository/request entrypoints with a typed Laya category, verified evidence, and deterministic baseline are wired; irrelevant deterministic, administrative, mutation, or high-impact endpoints remain outside Laya.
7. Direct repository delegation and repository solve both use typed model-route advice where verified distinct model choices exist; role mapping and quality/risk gates prevent invalid or lower-quality downgrades. Delegation advice remains metadata-only.
8. Eligible low-risk repository solve requests with verified evidence also receive taskless subagent-budget advice using deterministic `single_agent` baseline; suggestion never launches or changes worker/agent planning.
9. The dashboard distinguishes request-scoped from task-scoped decisions and reports eligibility, status, fallback and runtime evidence honestly.
10. Codex, Antigravity/Gemini, Claude, and every other enabled provider receive matching instructions and working MCP setup; provider-specific hooks/plugins load only in documented layouts.
11. Provider identity, permissions, repository/request scope, privacy bounds, and deterministic high-impact gates remain enforced.
12. Setup and diagnostics report per-provider installation and live-handshake state accurately; documentation does not claim unverified coverage.
13. Focused automated checks cover each changed adapter and Laya route. Host/runtime acceptance is reported separately for clients unavailable in the current environment.

## Implementation sequence

1. Inventory enabled providers and current source/test coverage; inspect dirty work without overwriting it.
2. Reconcile the existing Laya and provider-routing plans to this steering and split work by independently testable subsystem.
3. Inventory each request entrypoint and wire the shared active Laya runtime wherever typed decisions have verified evidence and a deterministic baseline, including taskless request scope; preserve explicit exclusions and fallback behavior.
4. Normalize each provider's MCP, skill/instruction, plugin, and hook packaging to current host formats; update setup and status reporting.
5. Validate each changed surface and record which installed clients completed a real handshake.

## 2026-11-24 request-scope observability correction

- The typed category option map is the single source for telemetry validation; new decision categories must be recorded and counted without a second allowlist drifting behind the runtime contract.
- The dashboard lists all supported typed categories and reports eligibility plus request/task scope. Request-scoped records remain telemetry-only and never become task-linked supervised candidates.
- All routing and context-budget influence in repository solve flows through typed decisions and their deterministic baselines. Legacy coordinator suggestions cannot make an untyped model or budget adjustment.
- Direct repository delegation preserves an explicit operator-selected model; Laya model routing applies only when no model was explicitly supplied and verified evidence supports multiple routes.

## 2026-11-24 remaining request-entrypoint coverage

- Apply registered low-risk Laya decisions across public request entrypoints, not only repository solve/delegate. A repository-bound `delegate`, `review`, `reason`, or `second_opinion` may use model-route advice when it has an authorized root, current EvidenceStore IDs verified under that canonical root, at least two digest-verified distinct routes, and a deterministic role baseline.
- `review_diff` passes its authorized root and current verified evidence to its bounded review calls when available. Chunking, fixed-latency FIM completion, deterministic compression, tool execution, and mutation paths keep their existing deterministic or explicit route unless a matching typed category can safely govern them.
- Repository-bound `generate_tests` and non-cascade `speculative_draft` may apply quality-preserving model-route upgrades against verified source evidence. Explicit draft models and configured cascade stages remain authoritative.
- Long repository-scoped narrative compression may use the registered context-budget category to choose a compact or standard chunk budget. It runs only after deterministic compression declines and never stores the text as training content.
- Adaptive repository context packs may use typed retrieval-strategy advice after their initial pack yields current EvidenceStore evidence. Rebuild context only for a valid suggestion; keep the first hybrid pack on advisory or rerun failure. Fast and full modes remain unchanged.
- Direct `local_ai_rag(action="search")` may reuse the adaptive pack's verified typed retrieval strategy. Only `dense_rag` and `lexical_bm25` map to the direct search modes; absent/invalid advice preserves semantic search plus its existing embedding-failure lexical fallback, while an empty/failed Laya-selected lexical search retries the semantic baseline. The response records the selected strategy/fallback.
- Context-source choice stays an explicit request-scoped advisory for a caller-identified unresolved evidence gap. Adaptive context packs currently expose neither a typed gap signal nor aligned source freshness/coverage and memory record provenance, so they must not synthesize those fields to trigger a recommendation.
- Laya output remains an uncalibrated model estimate. Usage, status, latency, and fallback telemetry do not establish quality or business value; report measured impact only after matched labeled evaluation.
- Metadata telemetry may report whether a successful typed suggestion agrees with its deterministic baseline, including request-only scope. Agreement is decision alignment, not correctness or measured utility. Never write a Laya output back as its own expected training label.
- Request-scoped decisions never require `task_id` or `session_id`; request identity and repository identity are derived by the Hub. Explicit model selections, high-risk quality floors, provider permissions, and deterministic fallbacks remain authoritative.
- Test each newly wired public entrypoint for a taskless request with verified evidence, explicit-model preservation, missing/stale evidence fallback, and no task-bound capture.

## 2026-11-25 direct generation proxy integration

- For `/api/chat` and `/api/generate`, evaluate typed `model_route` advice only when the caller omits `model`, supplies a repository root accepted by the Hub authorization policy, and the request contains a usable prompt. Use the deterministic router as baseline and the existing model-route eligibility, evidence-verification, digest, role, and quality gates.
- Keep these request decisions taskless. Do not require or fabricate `task_id` or `session_id`; do not make request-only inference a supervised candidate.
- Validate the root at the HTTP boundary and remove it from the body sent to Ollama. Rootless direct inference remains unchanged. Explicit caller models remain authoritative. `/api/embed`, streaming, task lifecycle, permission, mutation, and high-risk paths do not use this advisory.
- On unavailable Laya, missing/stale evidence, ambiguous route, abstention, or invalid suggestion, use the existing configured model and proxy path without failing the request.
- Acceptance: focused tests prove chat/generate model selection, explicit-model and rootless bypass, HTTP root authorization/binding, and that repository identity is not forwarded upstream.

## 2026-11-25 request API and observability correction

- Expose active request decisions through the repository-scoped `local_ai_coord(action="laya_decision")` operation and dedicated `POST /api/laya/decision` endpoint. This inference path must not be nested under `curate_dataset`, `/api/agent-state/tasks`, or gated on Agent OS being enabled. Require a canonical authorized repository root and server-verified evidence for every decision.
- Keep `curate_dataset` for candidate review, labels, evaluation snapshots, and export. Task-linked supervised candidate capture remains bound to a verified task/session. Do not accept request decisions as candidate curation or training labels.
- `laya_decision` accepts only typed `evaluate_decision`, `evaluate_context_source`, and `runtime_status` operations. `task_id` is optional; when present, validate it under the authorized repository and derive session identity server-side. A taskless request records null task/session identity.
- Keep every eligible request path actively advisory when its registered typed category, verified evidence, deterministic baseline, and risk gates qualify. Valid low-risk suggestions may affect the central route/context decision; permission, mutation, explicit model, quality, and latency gates remain authoritative. No arbitrary request-count limit applies.
- Dashboard separates request/task scope and reports eligibility, successful/abstained/invalid decisions, latency, fallback, and deterministic-baseline agreement. Baseline agreement is not correctness or utility. Preserve `UNCALIBRATED` until independent, matched, labeled evaluation supports calibration; never self-label Laya output.
- Acceptance: MCP schema and HTTP route expose taskless request decisions without Agent OS task requirements; taskless evidence/provenance and fallback tests pass; candidate capture still rejects absent/unverified task identity; docs and live tool description no longer route inference through dataset curation.
