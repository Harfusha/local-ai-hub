# Local Model Fine-Tuning Scaffold Implementation Plan

> **For agentic workers:** Implement in the current checkout. Preserve unrelated dirty work. No training, project-corpus generation, model promotion, or network upload during scaffold work.

**Goal:** Add manifest-driven local tooling for teacher-card generation, LoRA fine-tuning, and paired base-versus-adapter evaluation across preprocessing and decision-model tasks.

**Architecture:** A small Python package under `tools/model_training/` owns manifest/data validation, local teacher-card generation, LoRA training, and paired evaluation. Examples and a runbook define the preprocessing and decision-model workflows without changing production routing.

**Tech Stack:** Python 3.11+, PyTorch, Transformers, PEFT, Accelerate, local Ollama HTTP API, JSONL manifests.

## Tasks

- [x] Add tests for manifest validation, group/hash leakage rejection, and strict GPU selection.
- [x] Implement shared JSONL/manifest validation and provenance hashing.
- [x] Implement explicit-root, local-Ollama teacher-card generation with resumable outputs.
- [x] Implement config-driven LoRA/optional QLoRA training with CUDA acceleration and recorded runtime metadata.
- [x] Implement base-only baseline and paired base/adapter benchmark reports for schema, task facts/labels, latency, and token counts.
- [x] Add preprocessing and decision-model example manifests plus operator documentation.
- [x] Run focused scaffold tests and CLI validation only; no project corpus generation, model training/download, production routing change, or upload.
