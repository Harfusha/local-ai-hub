# Laya Active Decision Service, MCP/API, and Training Capture

**Operator steering (2026-11-10):** Laya should be used wherever it improves reliability, quality, speed, or enables useful new behavior. It must be callable through MCP/API. Collect all data useful for future Laya training; raw content is authorized when it is needed to form a useful training example.

## Goal

Make Laya a shared, typed decision service inside Local AI Hub. Reuse the current app, scheduler, runtime, task/evidence authorization, state directory, telemetry, reporting, and candidate curation. Create no per-agent daemon. Deterministic Hub rules remain authoritative for permissions, receipts, task lifecycle, commands, and execution.

## Decision surfaces

Implement typed, category-specific proposals for context source/quality, context budget, model route, redundant work, next step/diagnosis, delegation/review, completion gaps, and watchdog recommendations. Survey additional Hub decision points when source evidence shows a useful gap. Each category has a deterministic baseline, shadow comparison, independent labels, quality/latency/compute metrics, and its own activation gate. Keep categories shadow-only where no positive evidence exists. Advisory output cannot execute tools, grant permission, change task/receipt state, approve completion, or make a destructive decision. Filter route and operation options against server-verified availability. Abstention or failure preserves the baseline.

## MCP and HTTP

Expose a typed Laya decision request through an existing compact MCP tool and a root-authorized Hub HTTP API. Callers may select only a registered category and supply bounded input/evidence IDs. The server chooses mode, resolves repository/task/session identity, validates evidence and options, and applies category gates. Never accept caller-supplied identity, authorization, arbitrary tool execution, or a mode override. Direct API/MCP requests return explicit proposal, abstention, or unavailable status. API errors do not affect ordinary Hub behavior.

## Runtime lifecycle

Load Laya on its first request and retain the loaded session until 600 seconds of inactivity after the latest completed Laya request. Every later request resets the idle deadline; never unload while a request is in flight. Do not reject Laya solely because another model is loaded or a GPU reservation exists. Never evict, preempt, unload, or reconfigure another model. Preserve the configured hardware profile and CPU fallback. If actual provider or device capacity prevents Laya from loading, return an explicit isolated unavailable result and preserve deterministic Hub behavior. Use the existing Hub runtime; create no separate daemon.

## Training capture

Capture actual eligible Laya decision examples and useful outcomes: the minimum raw request/context needed to reproduce the decision, authorized evidence/source references and hashes, deterministic baseline proposal, Laya output, subsequent accepted/rejected/overridden outcome where observable, human labels, model/runtime/provider identity, latency, token/compute metadata, and failures/abstentions. Raw prompts, responses, and source excerpts may be stored when they materially improve training value. For the current context-source pilot, pass the task query and relevant retrieved excerpts only; recognized credential/token/password patterns are redacted, each field is bounded to 8 KiB and combined raw content to 16 KiB. Record which fields were redacted and which were unavailable. Exclude unrelated private content and fields with no training purpose; do not store unrelated Hub conversations just because they exist.

Deterministic baselines are derived by the Hub, never asserted by the caller. `context_source` records the authorized retrieval rank-order baseline. `completion_gap` records `ready` when the Agent OS completion gate passes and `not_ready` when it raises `CompletionGateError`; its evidence ID must be both verified in the request and present in the current task checkpoint. Other gate failures propagate as failures, not as `not_ready`. For categories without a registered server baseline, candidate metadata stays `baseline.status=not_available` and cannot support paired evaluation until that category receives a deterministic baseline implementation.

Natural capture, storage, human review, labeling, and export must not require per-example consent, a consent receipt, or separate per-example approval. Retired consent fields may be rejected, but must never gate those lifecycle stages. Existing repository authorization, access control, human-label verification, evidence provenance, deletion, and export safeguards remain required.

Keep examples local under configured state storage, repository/task/session scoped, access-controlled, revalidatable against current evidence, deletable with linked payloads and snapshots, and out of ordinary telemetry/logs/diagnostics. Preserve task/session/source group provenance to prevent split leakage. Model output is never a gold label. Training export contains only reviewed, independently verified labels and an explicit group-safe train split; validation and test examples remain separate. The current source-label rubric is `laya-source-label-v1`: select only a permitted source that best resolves the gap using relevance, freshness and coverage; do not invent evidence or treat Laya output as a label. Two annotators work independently, an independent adjudicator resolves disagreement, and a fourth independent reviewer verifies provenance and target. Collect data now; do not start fine-tuning or publish data without a separate request.

## Rollout and verification

Keep each category shadow until paired comparison shows noninferior decision quality and a measured improvement in reliability, quality, end-to-end latency, compute, or useful capability. Promote only the qualifying category to opt-in advisory; preserve a per-category off switch and deterministic fallback. Test MCP and HTTP contracts, identity and evidence authorization, redaction, capture scoping, deletion, dataset split, failure isolation, and concurrent lifecycle. Report source tests separately from installed live-model/provider evidence. Never claim device placement, quality, speedup, or memory release without direct measurements.
