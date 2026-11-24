# Qwen 3B Preprocessing Default Plan

**Spec:** [`../specs/2026-11-24-preprocess-qwen3b-default.md`](../specs/2026-11-24-preprocess-qwen3b-default.md)

1. [x] Merge the trained adapter with its exact base; create a Q4_K_M Ollama model and prepare a minimal, license-compliant public HF payload.
2. [x] Publish to the public `Harfusha` repo; record immutable commit, GGUF size, and SHA-256.
3. [x] Add the pinned artifact to the on-demand distribution registry; admit its model tag in Ollama preprocessing provisioning.
4. [x] Switch repository and current user preprocessing defaults to the trained tag; update model distribution/training docs and parent design.
5. [x] Verify the uploaded revision/file metadata, configuration parsing, Ollama model identity, and source diff. Do not run test suites unless requested.

## Evidence

- Training: [`state/experiments/model-training/runs/preprocess-card-qwen25-coder-3b-4096-20261124/qwen25-coder-3b/adapter/training_run.json`](../../../state/experiments/model-training/runs/preprocess-card-qwen25-coder-3b-4096-20261124/qwen25-coder-3b/adapter/training_run.json)
- 100-case paired benchmark: [`state/experiments/model-training/runs/preprocess-card-qwen25-coder-3b-4096-20261124/qwen25-coder-3b/benchmark-100case.json`](../../../state/experiments/model-training/runs/preprocess-card-qwen25-coder-3b-4096-20261124/qwen25-coder-3b/benchmark-100case.json)
- Public HF commit: [`Harfusha/local-ai-hub-preprocess-qwen25-coder-3b`](https://huggingface.co/Harfusha/local-ai-hub-preprocess-qwen25-coder-3b/tree/3e8c25fc7b6fd839701dad01dfe13a1ef4898543), verified public; GGUF size 1,929,902,656 bytes and LFS SHA-256 matches local artifact.
- Checks: anonymous HF HEAD returned 200 with the pinned size; TOML defaults/example/current user config parse to the trained tag; local Ollama reports the tag installed. First-use cache-miss download/registration on a separate clean machine was not executed.
