# High and Max Model Routing Implementation Plan

> **For agentic workers:** Use this plan task-by-task. User authorized native implementation in this session. Steps use checkbox syntax for tracking.

**Goal:** Align `high` and `max` model roles with available VRAM and use qualified Q4 model variants by default.

**Architecture:** `hardware.py` remains source of truth for hardware profile overrides. `max` uses a conservative 14B default, promotes only its heavy-code model at 32 GiB single-GPU VRAM, and no longer promotes models to FP4 from compute capability alone. Defaults and capability docs describe the same tags and estimates.

**Tech Stack:** Python profile configuration, TOML defaults, Markdown documentation.

**Spec:** `docs/superpowers/specs/2026-11-23-high-max-model-routing-design.md`

## Global Constraints

- Preserve all existing user changes.
- Do not download model weights.
- Keep preprocessing at `qwen2.5-coder:3b` in `high` and `max`.
- Use Q4_K_M weights and Q4 KV cache for revised profile roles.
- Do not enable an FP4 route without exact CUDA compatibility and a passing quality evaluation.

## Review Focus

- Missing or malformed per-GPU VRAM must leave `max` at the 14B heavy-code target.
- Multiple smaller GPUs must not be summed to trigger the 32B target.
- `has_fp4=true` must not change model tags by itself.
- Mirrored defaults and documentation must not claim that targets are installed or FP4-qualified.
- Existing uncommitted preprocessing corrections must remain intact.

---

### Task 1: Profile routing, quantization, and documentation

**Files:**
- Modify: `src/local_ai_hub/hardware.py`
- Modify: `defaults.toml`
- Modify: `src/local_ai_hub/defaults.toml`
- Modify: `docs/MODEL_CAPABILITIES.md`
- Review: `docs/agent-evaluation/fp4-blackwell-2026-11-02.md`

**Interfaces:**
- Consumes: `PROFILE_OVERRIDES`, `profile_overrides(profile_name, detected)`, per-GPU `vram_mb` and `has_fp4` metadata.
- Produces: Q4-tagged high/max targets; max 14B base with single-GPU 32 GiB heavy-code promotion; Q4 KV cache and matching estimate keys.

- [x] Set max baseline heavy/reasoning to `qwen2.5-coder:14b-instruct-q4_K_M`, general to `qwen3.5:9b-q4_K_M`, and KV cache to `q4_0`.
- [x] Use `qwen2.5-coder:32b-instruct-q4_K_M` for max heavy code only when one detected GPU reports at least `32768` MiB.
- [x] Remove automatic NVFP4 tag substitution based only on `has_fp4`; retain hardware capability reporting.
- [x] Add conservative VRAM estimate aliases for exact Q4 tags to both shipped TOML defaults.
- [x] Update the model routing matrix, max VRAM threshold, and FP4 qualification note in `MODEL_CAPABILITIES.md`.
- [x] Review diff and preserved working-tree changes; do not run tests.
