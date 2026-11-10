# Local Model Fine-Tuning Scaffold Implementation Plan

> **For agentic workers:** Implement in the current checkout. Preserve unrelated dirty work. No training, project-corpus generation, model promotion, or network upload during scaffold work.

**Goal:** Add manifest-driven local tooling for teacher-card generation, LoRA fine-tuning, and paired base-versus-adapter evaluation across preprocessing and decision-model tasks.

**Architecture:** A small Python package under `tools/model_training/` owns manifest/data validation, local teacher-card generation, LoRA training, and paired evaluation. Examples and a runbook define the preprocessing and decision-model workflows without changing production routing.

**Tech Stack:** Python 3.11+, PyTorch, Transformers, PEFT, Accelerate, local Ollama HTTP API, JSONL manifests.

## Tasks

- [ ] Add tests for manifest validation, group/hash leakage rejection, and strict GPU selection.
- [ ] Implement shared JSONL/manifest validation and provenance hashing.
- [ ] Implement explicit-root, local-Ollama teacher-card generation with resumable outputs.
- [ ] Implement config-driven LoRA training with CUDA acceleration and recorded runtime metadata.
- [ ] Implement paired base/adapter benchmark and JSON report for schema, task facts/labels, latency, and token counts.
- [ ] Add preprocessing and decision-model example manifests plus operator documentation.
- [ ] Run focused scaffold tests and CLI validation only; confirm no training, project scan, model pull, production routing change, or upload occurred.
