# Qwen 3B Preprocessing Default

## Goal

Use the trained Qwen2.5-Coder-3B QLoRA result for file-card preprocessing by default. Publish a self-contained Ollama-compatible model in the user's public Hugging Face account and fetch/register it on first use on clean installations.

## Decisions

- Publish `Harfusha/local-ai-hub-preprocess-qwen25-coder-3b` as a merged Q4_K_M GGUF. The trained artifact is a PEFT adapter; the published GGUF must include its merge with the exact Qwen2.5-Coder-3B-Instruct base.
- Preserve the upstream Qwen Research License Agreement and required attribution. Do not label the derivative Apache-2.0.
- Publish only inference weights, model card, upstream license, and required notice. Never upload training rows, evaluation rows, benchmark raw outputs, local paths, credentials, or temporary checkpoints.
- Pin the public repository commit and GGUF SHA-256 in the allowlisted model distribution registry.
- Set the repository default and current user preprocessing model to `qwen2.5-coder-prep-v4:3b`. Keep existing 0.5B and 1.5B alternatives available.
- Existing user overrides remain authoritative; first-use provisioning fails closed if download, hash verification, or Ollama registration fails.

## Acceptance

- Public HF repo is owned by `Harfusha`; its uploaded GGUF matches the local published file digest.
- A clean-cache first use downloads the pinned GGUF and registers the new Ollama tag; the same tag is the configured preprocessing default.
- Benchmark evidence is aggregate-only in the model card; raw cases stay local. The 100-case benchmark remains marked for manual source review.
- Targeted configuration and packaging checks pass. Full test suite is outside scope.

## Traceability

- Implementation plan: [`../plans/2026-11-24-preprocess-qwen3b-default.md`](../plans/2026-11-24-preprocess-qwen3b-default.md)
- Parent distribution design: [`2026-11-23-huggingface-model-auto-provisioning-design.md`](2026-11-23-huggingface-model-auto-provisioning-design.md)
