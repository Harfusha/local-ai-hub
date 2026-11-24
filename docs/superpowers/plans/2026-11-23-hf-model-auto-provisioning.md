# Hugging Face Model Auto-Provisioning Implementation Plan

> **For agentic workers:** Implement the selected model publication and lazy provisioning workflow task by task. Preserve the existing dirty checkout and do not upload before visibility is resolved.

**Goal:** Publish only selected trained models under `Harfusha` and make clean Local AI Hub installs lazily fetch them on first use.

**Architecture:** Publish curated model payloads only, with aggregate-only model cards. Use pinned Hugging Face commits for transformer/Laya models and pinned GGUF files for Ollama preprocessing. Cache on first use and verify hashes before loading.

**Tech Stack:** Hugging Face Hub API, `huggingface_hub`, Sentence Transformers, PEFT merge, llama.cpp conversion/quantization, Ollama.

**Spec:** `docs/superpowers/specs/2026-11-23-huggingface-model-auto-provisioning-design.md`

## Global Constraints

- Preserve all pre-existing dirty and untracked work in the shared `master` checkout.
- Do not upload datasets, raw benchmark rows, repository source, secrets, or rejected model candidates.
- Public visibility requires the user's choice and upstream license/training-data rights review.
- A private repo requires HF authentication on each new PC; public is required for a no-setup download.
- Keep general Hugging Face downloads and user model overrides unchanged.
- Do not add or run tests unless the user asks; use bounded static/manual verification.

## Review Focus

- A selected model is missing or the network is offline: use a cached verified snapshot or return a clear download error.
- A download has a mismatched hash: refuse to load it and keep the previous valid cache intact.
- A model repo is private and the current machine lacks a token: report the needed HF authentication without exposing credentials.
- A user configured a different model: keep that override and do not auto-substitute the trained model.
- A download is interrupted: do not leave a partial file registered or usable by Ollama.

---

### Task 1: Curate and stage selected model artifacts

**Files:**
- Modify: `tools/model_training/publish_hf.py`
- Create: a bounded temporary staging directory under the model-training state tree

**Interfaces:**
- Consumes the selected Laya checkpoint, merged embedding/reranker models, and selected preprocessing adapters.
- Produces model-only payloads and aggregate-only model cards for the uploader.

- [ ] Stage only required checkpoint/config/tokenizer/model files; never copy raw benchmark rows or training data.
- [ ] Merge and convert selected preprocessing adapters to Ollama-compatible GGUF files; record base revision and artifact SHA-256.
- [ ] Review staged file list and sizes before upload.

### Task 2: Add model-specific lazy download paths

**Files:**
- Modify: `src/local_ai_hub/embeddings.py`
- Modify: `src/local_ai_hub/reranker.py`
- Modify: `src/local_ai_hub/laya_runtime.py`
- Modify: `src/local_ai_hub/ollama.py`
- Modify: `src/local_ai_hub/model_distribution.py`
- Modify: default model configuration and `docs/MODEL_DISTRIBUTION.md`

**Interfaces:**
- Consumes the actual Hugging Face repository IDs, commit revisions, and SHA-256 values from Task 3.
- Produces cache-first, allowlisted resolution and first-use provisioning for only selected trained models.

- [ ] Add default trained embedding/reranker repo IDs with immutable revisions.
- [ ] Resolve selected Laya `hf://repo@commit` to the matching verified snapshot on first Laya load.
- [ ] Provision the selected preprocessing GGUF into Ollama only when the configured model is first requested.
- [ ] Preserve existing explicit model configuration and general download defaults.

### Task 3: Publish and verify selected repos

**Files:**
- Modify: `.local-ai-hub` plan state through the Local AI Hub plan API
- Update: `docs/superpowers/specs/2026-11-23-huggingface-model-auto-provisioning-design.md`

**Interfaces:**
- Consumes Task 1 staged artifacts and Task 2 resolver code.
- Produces actual Hugging Face repository commit IDs, pinned registry values, and a verified clean-cache download result.

- [ ] Create only the selected model repos under `Harfusha`, with visibility chosen by the user.
- [ ] Record repository commit IDs and model-file hashes; publish no dataset or raw case rows.
- [ ] Verify clean-cache download and subsequent cache reuse for each required backend.
- [ ] Verify the configured runtime routes load the selected model without manual model-ID setup.
