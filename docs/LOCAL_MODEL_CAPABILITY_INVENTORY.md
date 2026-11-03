# Local model capability inventory

This inventory follows MCP dispatch and the corresponding HTTP calls in
`src/local_ai_hub/mcp_server.py`. It describes code paths and configured gates;
it does not prove that a model is installed, that the backend is healthy, that
an action uses the GPU, or that output meets a quality threshold. The live
profile and configuration-level capability reasons are available from
`local_ai_status`.

Status capability states are `profile_blocked`, `feature_disabled` and
`enabled_by_operator`. The field `provider_readiness="not_checked"` is
deliberate: capability discovery does not infer installed models, quality or
live GPU use.

## Public MCP surface classification

The public MCP surface remains seven tools. The table classifies the tool
families by whether they submit local inference; it does not treat every
action in a mixed tool as model-backed.

| MCP tool | Local-model behavior | Baseline / admission notes |
| --- | --- | --- |
| `local_ai_status` | No inference. Reports configured profile and static capability states; transient readiness is not inferred. | Available at every profile. |
| `local_ai_task` | Mixed: semantic actions, compression, routing, generation, vision, transcription, browser interpretation, async jobs and evaluation are mapped individually below. | Capability registry filters profile/feature-gated actions; direct execution rechecks admission. Job status/wait/result/cancel remain available after downgrade. |
| `local_ai_repo` | Mixed: search/index/source/diff/impact/investigate/diagnose and checks are deterministic or indexed; `solve`, review/delegation and opt-in search summary can invoke models. | Profile policy filters registered semantic capabilities; deterministic evidence remains authoritative. Search summary requires both operator flag and per-call opt-in. |
| `local_ai_rag` | Mixed provider path: retrieval/index/ingestion can use embeddings; `search` may optionally run the configured cross-encoder reranker. No LLM synthesis is implied. | Reranking requires `balanced+`, `features.local_reranking=true`, and a usable non-CPU reranker device. Embedding/device use depends on its separate provider configuration. Root-bound project actions require an authorized root/workspace; owner-global docsets retain their separate namespace. |
| `local_ai_coord` | No local inference. Coordination, task, memory, plan, lease and verification operations are stateful deterministic operations. | Existing scope, ownership and authorization contracts remain controlling. |
| `local_ai_work` | Bounded local model execution only for explicitly admitted `submit`; planning/execute modes are not implied by the model profile. | `submit` requires `high`/`max`, bounded mode, feature flag and exact permissions/scope. Recovery actions remain available at every profile subject to owner checks. |
| `local_ai_artifact` | No local inference. Exact source/artifact reads and persisted evidence retrieval. | Root/workspace confinement and artifact authorization remain controlling. |

## Current capability matrix

| Capability | `cpu` / `integrated` / `low` | `balanced` | `high` / `max` | Admission and quality state |
| --- | --- | --- | --- | --- |
| Deterministic repo search, source, symbols, diff and impact | Available | Available | Available | Deterministic/indexed evidence; no inference required. |
| RAG embedding retrieval | Available when provider is configured | Same | Same | Provider/device-specific; installation, latency and GPU placement are not established by capability discovery. |
| RAG cross-encoder reranking | Hidden | Optional | Optional | Requires `features.local_reranking=true`, a usable non-CPU reranker and role evaluation. Feature defaults off; quality not qualified. |
| Long search-result summary | Hidden | Optional | Optional | Requires `features.search_summaries=true` and per-call `summarize_results=true`; exact results remain authoritative. Summary quality requires evaluation. |
| Cross-file semantic analysis/design | Hidden | Hidden | Optional | Requires `features.local_semantic_analysis=true`; advisory only. Current target-model evaluation is absent. |
| Vision and code generation | Hidden | Hidden | Optional | Separate default-off role flags; provider support and role evaluation required. Quality not qualified. |
| Bounded file edits | Hidden | Hidden | Optional | Requires bounded mode, `features.bounded_local_work=true`, evaluated task type, explicit scope/permissions, broker fences and primary-agent review. Quality not qualified. |
| Model availability / measured quality | Not established | Not established | Not established | Status/configuration are not proof of installed route, live health, GPU use, or task quality. See measurement gaps below. |

HTTP paths below are mapped from MCP dispatch or execution code; asynchronous
submission routes are not themselves model endpoints. The seven-tool split
and the per-action operation contract are implemented in
`src/local_ai_hub/mcp_server.py` and `src/local_ai_hub/operation_contracts.py`.

## Local-model and model-adjacent routes

| Surface / action | HTTP route or behavior | Profile policy | Readiness / authority |
| --- | --- | --- | --- |
| `local_ai_task: compress`, `route` | `/api/compress`, `/api/route` | Available from `cpu` through `max` | Requires a configured healthy model route; compression is bounded and advisory. |
| `local_ai_task: submit` with `job_action` | `/api/async-jobs` then the mapped semantic route, including `speculative_lint` | `balanced` for semantic/review jobs; `high` for code-generation jobs; same role flags as foreground calls | Job admission checks the underlying action's profile and feature gate. Existing `status`, `wait`, `result` and `cancel` controls stay available after downgrade. |
| `local_ai_task: delegate`, `explore`, `reason`, `review`, `second_opinion`, `continue`, `batch`; `local_ai_repo: delegate`, `review_diff` | `/api/delegate`, `/api/reason`, `/api/review`, `/api/second-opinion`, `/api/conversations/continue`, `/api/delegate/batch`, `/api/delegate/repo`, `/api/review/diff` | `balanced` for analysis/review/delegation | Semantic output is advisory; deterministic/indexed evidence remains authoritative. Direct MCP and HTTP calls share gates. |
| `local_ai_repo: solve` | `/api/solve/repo` | `high`, plus `features.local_semantic_analysis=true` | Read-only cross-file analysis/design through the bounded tool-aware agent (maximum 3 model steps and 6 tool calls). Returns deterministic/context evidence and confidence; response size is capped and cancellation is honored. Output is advisory; it does not authorize edits. Task-specific evaluation remains required before promotion. |
| `local_ai_task: vision` | `/api/task/vision` | `high` and `max`, plus `features.local_vision=true` | Default-off vision release flag; requires vision-role evaluation and provider support. |
| `local_ai_task: complete_code`, `scaffold`, `speculative_draft` | `/api/complete`, `/api/task/scaffold`, `/api/task/speculative_draft` | `high` and `max`, plus `features.local_code_generation=true` | Default-off code-generation release flag; proposals do not authorize direct file writes. |
| `local_ai_task: automation` | `/api/task/automation` | `high` and `max`, plus `features.local_automation=true` | Separate default-off automation release flag; existing task, browser and permission contracts remain authoritative. |
| `local_ai_repo: search` with `summarize_results=true` | Deterministic `/api/search`, then optional `/api/compress` over at most 8 bounded matches / 12,000 valid JSON characters | `features.search_summaries=true` plus per-call opt-in; `balanced` and above | Disabled by default. Exact matches and pagination remain authoritative. Summary is separately returned and advisory. Every `[path:start-end]` citation must match a supplied search path and line range; missing, invented or out-of-range citations reject the summary while preserving exact results. Absolute root is not sent to compression; a root fingerprint and source evidence IDs bind the summary context. Truncated generation is rejected. Hard HTTP timeout is at most 15 seconds. |
| `local_ai_work: submit` | `/api/work-orders` | `high` and `max`, `mode="bounded"`, plus `features.bounded_local_work=true` | Default-off release flag after task-specific quality evaluation; explicit task scope/permissions and primary-agent diff/test review remain mandatory. Direct HTTP submissions use the same gates. |
| `local_ai_work: status`, `wait`, `get`, `cancel` | `/api/work-orders` | Every profile | Existing-job recovery stays discoverable after downgrade, subject to owner and authorization checks. |
| `local_ai_task: benchmark`, `hardware_benchmark`, evaluation actions | `/api/benchmark`, `/api/benchmark/run`, `/api/evaluation`, `/api/task/eval_suite`, `/api/task/prompt_eval`, `/api/task/eval_drift` | Discovery is not a readiness or promotion grant | Hardware benchmark and `eval_suite` submit inference through the injected model scheduler, record queue wait / sampled peak VRAM, and preserve admission/timeout identity. Pending evaluations are marked not started; dispatched timeouts are non-retryable unknown outcomes. Runner completion is not model-quality acceptance. |
| `local_ai_task: transcribe` | `/api/task/transcribe` | Every profile | Separate transcription provider/cache policy; CPU execution is not GPU use. Downloads remain opt-in. |
| `local_ai_task: browser` | `/api/task/browser` | Every profile | Browser capture can be separate from its optional model interpretation; availability depends on the configured browser/provider path. |

## Deterministic and model-adjacent operations

Repository search without `summarize_results=true`, `local_ai_repo: investigate`
(`/api/repo/investigate`), `diagnose` (`/api/repo/diagnose`), code indexes,
source reads, diffs, symbol lookup and repository checks remain
deterministic/indexed MCP operations. Existing operations cover the planned
model-assisted follow-ups:

| Deterministic result | Existing model follow-up | Decision |
| --- | --- | --- |
| `review_diff` findings | `/api/review/diff` performs the existing feature-gated model review over the bounded diff. | Reuse this route; do not add a second summary layer over its generated findings. |
| `impact`, `refactor_impact` | Deterministic `/api/repo/impact` and `/api/refactor_impact`; explicit `local_ai_repo: solve` is available for evidence-grounded cross-file analysis. | Keep impact output authoritative and deterministic. No automatic synthesis is added; solve remains a separate, high-profile, feature-gated request. |
| Test or log output supplied by the caller | `local_ai_task: compress` accepts bounded caller-provided text. | Do not scrape files or logs automatically. Preserve the caller's selected input and existing privacy boundary. |
| RAG-backed `context` results | `local_ai_repo: context` retrieves/compiles evidence; `solve` can separately synthesize a requested analysis. | Keep retrieval evidence and generated synthesis distinct; do not imply RAG retrieval alone used an LLM. |

Embedding and reranking routes are provider-specific and separately configured;
this inventory does not infer their device or installed weights. Preprocessing
uses its configured preprocessing model and remains a background indexing path;
do not change its provider as part of tiering.

RAG search can invoke the configured cross-encoder only when the search request
asks for reranking, the reranker feature is enabled, and its configured device
is non-CPU. MCP search now requests it only when `features.local_reranking=true`
and the effective profile is `balanced` or higher. Direct `/api/rag/search`
requests enforce the same gate and cannot promote caller-supplied
`use_reranker=true`. The release flag defaults off. Retrieval and embedding
remain independently available according to their provider/device configuration;
they do not imply LLM synthesis or GPU placement. Reranker quality and live
device readiness remain unqualified until role evaluation and runtime evidence.

| RAG action | HTTP behavior | Model involvement and admission |
| --- | --- | --- |
| `search` | `/api/rag/search` | Embedding retrieval follows the configured embedding provider/device. Optional cross-encoder reranking is gated at `balanced+` by `features.local_reranking`; direct HTTP cannot override the gate. No generated answer is added. |
| `index`, `docset_index`, `docset_search`, `list`, `ingest_document`, `ingest_diagram` | MCP dispatch to the corresponding RAG service operations | Index/ingestion may use configured embedding or document/diagram processing providers; exact provider/device readiness is configuration- and operation-specific. These actions do not imply LLM synthesis or GPU placement. Project paths remain root-authorized; named docsets use owner-global namespace. |

## Measurement gaps

- Hardware benchmark evidence for the RTX 5070 Ti, driver/backend, model
  residency, peak VRAM, cold/warm latency, throughput and concurrency is not
  established by these source paths.
- The active Local AI Hub status reported Ollama online, `active_model=null` and
  unknown VRAM pressure. `hubctl status` and `ollama list` observed the managed
  Ollama + llama.cpp backend online, an RTX 5070 Ti with 15 GB reported VRAM,
  and 12 installed model tags. These are runtime/inventory snapshots, not proof
  of per-request GPU residency, speed or quality.
- A 40-token request for installed `qwen3.5:9b-nvfp4` returned a truncated
  hardware-benchmark envelope without usable performance fields. No model was
  pulled; benchmark evidence remains unestablished.
- A separate request for installed `qwen3.5:4b-nvfp4` failed with
  `CUDA endpoint state is not safely reserved; Ollama fallback blocked`.
  Source tracing found the benchmark path bypassed the scheduler preparation
  step; this is fixed and covered by scheduler integration tests. The deployed
  Hub was restarted from the repository and a post-fix run reached the model
  scheduler but timed out while still pending (`request_not_sent=true`,
  `operation_not_started=true`). No inference, provider fallback or model pull
  occurred; the physical benchmark remains unmeasured.
- After loading timeout observability, one bounded `qwen3.5:4b-nvfp4` run
  returned `wait_reason="gpu-reservation"`; the model request was not sent.
  The external reservation must be reconciled by its owner before another
  benchmark can provide GPU evidence.
- Scheduler timeout responses retain a safe `wait_reason`; status exposes only
  the coarse `gpu_admission_state` (never lease identity), and the operator
  dashboard displays it. These fields improve diagnosis; they do not prove
  device readiness or authorize retrying an unresolved inference.
- The current read-only evaluation report contained 0 matched tasks and returned
  `insufficient_evidence`; it does not qualify any model role or capability.
- Cases A1/A2 now define cross-file analysis and design evaluation inputs, but
  neither has a target-model run. No current task-specific result qualifies
  search summaries, analysis, vision or bounded edits. High/max profile
  exposure is a ceiling; existing evaluation and explicit-permission gates
  remain mandatory.
- `features.local_semantic_analysis`, `features.local_vision`,
  `features.local_code_generation`, `features.local_automation` and
  `features.bounded_local_work` and `features.local_reranking` default to
  false. Operators may enable each only after reviewing role-specific task
  evaluation; the flags are release controls, not proof or automatic evaluation.
- Other `/api/repo/*`, `/api/rag/*`, embedding/reranker and provider routes need
  per-operation execution evidence before being classified as local-model
  inference. An HTTP endpoint name alone does not establish model use.

## Baseline and provenance

- Implementation evidence is source-level; configured route/model names do
  not prove installation, health, GPU placement or output quality.
- The pre-change baseline revision for this plan was
  `5939aba3d8a4fc04eec3831da6ee2312bfc0a0d2`; the checkout already contained
  unrelated dirty changes. Preserve those changes during implementation.
- Profile exposure and generated guidance are covered by the parameterized
  operation-contract, feature and generator suites recorded in the plan's
  integrated checkpoint. Those tests are the deterministic baseline; they do
  not claim model inference.
- Search-summary edge tests now cover cancelled compression and contradictory
  matches that must both remain cited. The path is synchronous and persists no
  summary artifact, so stale persisted-summary rejection is not applicable.
- Existing plans/evaluation references: this implementation plan and
  `docs/agent-evaluation/local-model-gpu-cases.md`,
  `docs/agent-evaluation/local-model-gpu-scoring.md`. No separate task/chat is
  created for the same work.
