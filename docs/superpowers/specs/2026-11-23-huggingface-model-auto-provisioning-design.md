# Hugging Face Model Auto-Provisioning Design

## Goal

Publish only the selected trained model artifacts under the authenticated `Harfusha` account. A clean Local AI Hub installation should fetch each selected model from Hugging Face only when that model is first needed, then reuse the local cache.

## Selected artifacts

- Laya `run_expanded`: `Harfusha/local-ai-hub-laya-run-expanded`, native full checkpoint.
- BGE embedding: `Harfusha/local-ai-hub-bge-small-en-v1-5-code`, merged LoRA inference model.
- BGE reranker: `Harfusha/local-ai-hub-bge-reranker-v2-m3-code`, merged verified-LoRA inference model.
- Preprocessing Qwen 0.5B and 1.5B remain available as alternatives. The new trained Qwen 3B default is `Harfusha/local-ai-hub-preprocess-qwen25-coder-3b`, merged QLoRA GGUF Q4_K_M.

Do not publish training/evaluation datasets, raw benchmark rows, source repositories, credentials, temporary checkpoints, or duplicate full-training candidates. Model cards may contain aggregate metrics and the upstream base revision only.

## Runtime behavior

- Embedding and reranker use exact Hugging Face repository IDs and pinned commit revisions through their existing Sentence Transformers loaders.
- Laya resolves its configured allowlisted repository and pinned commit on its first runtime load and verifies the expected file hashes.
- Preprocessing uses the selected local Ollama tag. Before its first chat request, the Hub downloads the pinned GGUF into its state model cache, verifies SHA-256, and registers the model with Ollama. Later requests reuse the registered model.
- Download permission is allowlisted to these selected trained artifacts. Existing user model overrides and unrelated Hugging Face download policy stay unchanged.
- Missing network, authorization, revision, or hash verification fails closed with a clear error; it never substitutes a base model silently.

## Visibility and fresh PCs

The user selected public repositories, so a new PC can download without Hugging Face authentication. Upstream licenses and training-data handling were reviewed; only curated inference files and aggregate-only cards are published. No source rows or raw benchmark cases are included.

## Verification

Verify each staged payload contains only the intended model files and model card. After publishing, record the actual repository commit and file hashes. On a clean cache, verify one lazy download per model family, subsequent cache reuse, hash rejection, and the private-repository authentication error path where applicable.
