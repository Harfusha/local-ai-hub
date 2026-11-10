# Local Model Fine-Tuning Scaffold

## Goal

Add reusable, local-first tooling in Local AI Hub for selecting model and dataset, generating preprocessing-card targets with the configured 3B teacher, fine-tuning a chosen base model, and comparing base versus adapter on held-out cases. The same manifest and runner must support the future decision-model dataset.

## Scope

- Keep the tooling under `tools/model_training/`; document the operator workflow in `docs/MODEL_TRAINING.md`.
- Support preprocessing targets `Qwen/Qwen2.5-Coder-0.5B-Instruct`, `Qwen/Qwen2.5-Coder-1.5B-Instruct`, and `Qwen/Qwen2.5-Coder-3B-Instruct`. The machine's configured `qwen2.5-coder:3b` is the local card-generation teacher for the current `high` profile.
- Accept arbitrary explicit base model IDs/paths and task datasets for decision-model fine-tuning. Do not infer or change the production decision-model route.
- Consume explicit project roots and JSONL output paths. Do not enumerate or process all machine projects unless the operator runs that command with those roots.
- Generate cards through the local Ollama API only. Never send project source to a cloud service.
- Use grouped train/evaluation splits and reject overlapping groups, IDs, or source hashes.
- Fine-tune with LoRA. Require CUDA by default; fail clearly when unavailable. Permit CPU only by explicit config. Prefer BF16, SDPA, gradient checkpointing, fused AdamW, and bounded batches when supported; offer explicit 4-bit QLoRA for larger models; record actual choices.
- Benchmark base and adapter with identical prompts, schema, decoding settings, and held-out cases. Record schema/task scores, unsupported claims when supplied, token counts, latency, runtime, model revisions, and dataset hashes.
- Keep all datasets, checkpoints, adapters, and reports in caller-selected output directories. No automatic model promotion, Hugging Face login, repo creation, or upload.

## Canonical Inputs

- A run manifest names task, base model, train JSONL, held-out benchmark JSONL, output directory, prompt/schema, LoRA parameters, and hardware/precision policy.
- Training JSONL rows contain a unique `id`, non-empty `group_id`, source/dataset provenance, and three chat messages (`system`, `user`, `assistant`).
- Benchmark JSONL rows contain a unique `id`, `group_id`, and the same inference inputs plus task-specific expected output/facts/forbidden claims.
- Preprocessing card rows preserve source path and SHA-256. Decision-model rows preserve caller-supplied provenance without requiring source-code fields.

## Acceptance

1. A manifest validator rejects malformed rows, missing provenance, invalid schemas, duplicate IDs, and train/evaluation leakage before loading model weights.
2. Card generation uses the local configured teacher, exact file-card schema, resumable JSONL output, source hashes, and explicit roots.
3. Training selects CUDA and accelerated precision/attention where supported, records actual settings, and never silently falls back to CPU.
4. Paired benchmark loads base and adapter under one runtime, preserves identical cases/settings, and writes machine-readable per-case and aggregate results.
5. Example manifests cover both preprocessing cards and a generic decision-model task.
6. No current project corpus is generated, no model is trained, and no production model/configuration is changed while building the scaffold.

## Distribution

Publishing is a later explicit action. The first release should be a private Hugging Face model repository under the user's account; upload only the adapter/model card and safe provenance, never private project source or generated training cards. Public release requires a base-model license review, dataset-rights review, and a completed evaluation report.
