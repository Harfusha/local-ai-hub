# Laya Active Decision Service, MCP/API, and Training Capture

**Operator steering (2026-11-10):** Laya should be used wherever it improves reliability, quality, speed, or enables useful new behavior. It must be callable through MCP/API. Collect all data useful for future Laya training; raw content is authorized when it is needed to form a useful training example.

## Goal

Make Laya a shared, typed decision service inside Local AI Hub. Reuse the current app, scheduler, runtime, task/evidence authorization, state directory, telemetry, reporting, and candidate curation. Create no per-agent daemon. Deterministic Hub rules remain authoritative for permissions, receipts, task lifecycle, commands, and execution.

## Decision surfaces

Implement typed, category-specific proposals for context source/quality, context budget, model route, redundant work, next step/diagnosis, delegation/review, completion gaps, and watchdog recommendations. Survey additional Hub decision points when source evidence shows a useful gap. Each category has a deterministic baseline, shadow comparison, independent labels, quality/latency/compute metrics, and its own activation gate. Keep categories shadow-only where no positive evidence exists. Advisory output cannot execute tools, grant permission, change task/receipt state, approve completion, or make a destructive decision. Filter route and operation options against server-verified availability. Abstention or failure preserves the baseline.

## MCP and HTTP

Expose a typed Laya decision request through an existing compact MCP tool and a root-authorized Hub HTTP API. Callers may select only a registered category and supply bounded input/evidence IDs. The server chooses mode, resolves repository/task/session identity, validates evidence and options, and applies category gates. Never accept caller-supplied identity, authorization, arbitrary tool execution, or a mode override. Direct API/MCP requests return explicit proposal, abstention, or unavailable status. API errors do not affect ordinary Hub behavior.

## Training capture

Capture actual eligible Laya decision examples and useful outcomes: the minimum raw request/context needed to reproduce the decision, authorized evidence/source references and hashes, deterministic baseline proposal, Laya output, subsequent accepted/rejected/overridden outcome where observable, human labels, model/runtime/provider identity, latency, token/compute metadata, and failures/abstentions. Raw prompts, responses, and source excerpts may be stored when they materially improve training value. Exclude credentials/secrets, unrelated private content, and fields with no training purpose; record redaction and missing-data reasons. Do not store unrelated Hub conversations just because they exist.

Keep examples local under configured state storage, repository/task/session scoped, access-controlled, revalidatable against current evidence, deletable with linked payloads and snapshots, and out of ordinary telemetry/logs/diagnostics. Preserve task/session/source group provenance to prevent split leakage. Model output is never a gold label. Training export contains only reviewed, independently verified labels and an explicit group-safe train split; validation and test examples remain separate. Collect data now; do not start fine-tuning or publish data without a separate request.

## Rollout and verification

Keep each category shadow until paired comparison shows noninferior decision quality and a measured improvement in reliability, quality, end-to-end latency, compute, or useful capability. Promote only the qualifying category to opt-in advisory; preserve a per-category off switch and deterministic fallback. Test MCP and HTTP contracts, identity and evidence authorization, redaction, capture scoping, deletion, dataset split, failure isolation, and concurrent lifecycle. Report source tests separately from installed live-model/provider evidence. Never claim device placement, quality, speedup, or memory release without direct measurements.