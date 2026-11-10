# Local Model Fine-Tuning Scaffold Implementation Plan

> **For agentic workers:** Implement in the current checkout. Preserve unrelated dirty work. No training, project-corpus generation, model promotion, or network upload during scaffold work.

**Goal:** Add manifest-driven local tooling to train and benchmark preprocessing models and the native Laya typed-decision model, with datasets sourced from existing Hub data.

**Architecture:** A small Python package under `tools/model_training/` owns manifest/data validation, read-only export of persisted Hub cards, backend dispatch, and paired evaluation. Transformers LoRA stays the causal-LM backend. Laya uses its pinned native trainer/evaluator, grouped decision JSONL, and native checkpoint layout. Neither backend changes production routing. New card generation is not part of training data collection.

**Tech Stack:** Python 3.11+, PyTorch, Transformers, PEFT, Accelerate, pinned optional `laya==0.4.30`, local Ollama HTTP API, JSONL manifests.

## Tasks

- [x] Add tests for manifest validation, group/hash leakage rejection, and strict GPU selection.
- [x] Implement shared JSONL/manifest validation and provenance hashing.
- [x] Keep explicit-root local-Ollama card generation separate from training-data collection.
- [x] Export existing indexed file/module/project cards and matching existing source/card pairs without model calls.
- [x] Add project-held-out embedding corpus split with exact-card duplicate protection and no invented relevance labels.
- [x] Implement config-driven LoRA/optional QLoRA training with CUDA acceleration and recorded runtime metadata.
- [x] Implement base-only baseline and paired base/adapter benchmark reports for schema, task facts/labels, latency, and token counts.
- [x] Add preprocessing and decision-model example manifests plus operator documentation.
- [x] Add Laya-specific manifest/data validation and deterministic group-safe split.
- [x] Add pinned Laya native training and official-evaluator benchmark to the existing matrix orchestrator.
- [x] Add a canonical Laya matrix example, optional requirements file, and backend-specific runbook.
- [x] Restore explicit per-example consent and unique receipt enforcement for Laya capture, runtime evaluation, merge/export, and existing-card export; preserve registered-root, source-hash, task/session, evidence, verified-label, and deterministic-card filters.
- [x] Confirm receipt uniqueness, deletion tombstones, selective export, and receipt-digest provenance with focused tests.
- [x] Specify the approved metadata-only `context_source` pilot: unresolved gap, multiple authorized sources, code-only inputs, blind independent labels plus adjudication, and paired deterministic baseline.
- [x] Connect an explicit `curate_dataset` `evaluate_context_source` shadow operation to the local pinned Laya adapter; derive repository/task/session identity on the server, validate evidence before inference, and capture only the actual outcome through the scoped recorder. Ordinary Hub routing is unchanged.
- [ ] Configure and invoke the pinned local runtime only after separate operator authorization. Runtime defaults disabled and no inference or training was run in this tooling task; no new Laya examples or model-quality claim are established.
- [x] Run static Python, lint, CLI, manifest, and diff checks only; no training, model download, live benchmark, routing change, or upload.
