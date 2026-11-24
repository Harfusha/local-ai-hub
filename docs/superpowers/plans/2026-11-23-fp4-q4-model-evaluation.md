# All-Tier FP4 vs Q4 Model Evaluation Plan

> **For agentic workers:** Follow this plan in order. Keep GPU inference stopped until the RTX 5070 Ti is free and has safe memory headroom.

**Goal:** Measure quality, successful task completion, latency, throughput and VRAM for every distinct tier model/role, comparing FP4 against a clearly identified Q4 baseline.

**Architecture:** Test each unique model-role pair once, even when several tiers reuse it. Compare the exact configured Q4 artifact with a model-matched NVFP4 path using identical prompts and settings. Separate quality outcomes from speed claims whenever runtimes differ.

**Tech Stack:** Ollama HTTP API; isolated Transformers 5.24.0 environment with NVFP4 kernels and BitsAndBytes Q4 NF4; host Python checks for deterministic task outputs; `nvidia-smi`.

**Spec:** `docs/superpowers/specs/2026-11-23-installer-fp4-model-audit.md`

## Global Constraints

- User authorized required model downloads and conversions for this evaluation.
- Do not start inference while user applications occupy the GPU; do not close or interrupt them.
- Use same source checkpoint, prompt set, context length, max output, temperature and seed inside every controlled pair.
- Treat BitsAndBytes NF4 only as an optional GPU based diagnostic baseline; it is not Q4_K_M and does not prove native NVFP4 Tensor Core acceleration.
- Record exact Q4 quantization and runtime for every baseline; do not assume every `Q4` tag means Q4_K_M.
- Claim FP4 hardware acceleration only when the actual NVFP4 kernel/runtime path is observed on the GPU, with no CPU or disk offload.
- Report each role and exact model ID, artifact source/digest, quantization, runtime, settings, quality result, latency, throughput, peak VRAM, and limitation.
- Do not promote a route based only on hardware or published-tag support. Require model-specific quality and runtime evidence.

## Review Focus

- **Runtime mismatch:** exact Ollama Q4_K_M and Transformers NVFP4 results are separate comparisons unless both variants run through the same backend.
- **Different source weights:** reject a pair if base revision or tokenizer differs.
- **VRAM interference:** do not load if user processes remain active or available memory is below the model's measured load requirement.
- **Vision inconsistency:** send identical image bytes and question to both variants; record image preprocessing and resolution.
- **Small-sample overclaim:** report per-case score and count; call a variant better only when measured results support it.

---

## Model and Role Matrix

Deduplicate repeated tiers, preserve every role. Exact names and conditional branches must be rechecked against the active `PROFILE_OVERRIDES` before execution.

| Model family/size | Tier roles represented | Case set |
|---|---|---|
| Qwen2.5-Coder 0.5B | CPU preprocessing | symbol/card extraction |
| Qwen2.5-Coder 1.5B | integrated/low/balanced preprocessing; fast code; small subagent | extraction; short code patch |
| Qwen2.5-Coder 3B | CPU/integrated/low general and heavy code; balanced fast; medium/high/max preprocessing; high background | general instruction; extraction; code patch |
| Qwen2.5-Coder 7B | integrated/low reasoning; balanced general/heavy/subagent; medium/high/max fast; medium background; max background | root-cause; general; fast edit; involved code edit |
| Qwen2.5-Coder 14B | high heavy/subagent; max heavy/reasoning/subagent | multi-file code change; root-cause |
| Qwen2.5-Coder 32B | conditional max heavy route for sufficiently large GPU | multi-file code change; classify unsupported if host cannot load |
| Qwen3.5 9B | balanced/medium reasoning and general; high reasoning/general; max general | reasoning; general instruction |
| Qwen3-VL 4B | CPU/integrated/low vision | visual QA set |
| MiniCPM-V 8B | balanced/medium/high/max vision | visual QA set |

Subagent entries reuse the corresponding model/role cases above; do not repeat a case solely because another tier points to the same exact model and role.

## Comparison Rules

1. **Primary product A/B:** compare each exact configured Q4 model against FP4 made from the same model source/revision, with the same tokenizer, prompts, context, output limit, temperature and seed. Use the actual serving runtime available for each format; if runtimes differ, compare quality but report latency/throughput as cross-runtime measurements, not as quantization-only effects.
2. **Same-runtime proof:** use identical backend/API only when that backend accepts both quantizations. The approved `qwen3.5:9b-nvfp4` and `qwen3.5:9b-q4_K_M` Ollama pair is the clean same-runtime A/B; apply identical API overrides.
3. **NF4 diagnostic only:** optional Transformers BitsAndBytes NF4 can verify a CUDA 4-bit baseline and model quality, but label it `NF4`, never `Q4_K_M` or native FP4. Its CUDA acceleration does not establish native NVFP4 Tensor Core acceleration.
4. **Unavailable pairs:** record `not available`, `gated`, `load failed`, or `hardware limit` with source and exact error. Never substitute a different model size/family and call it an A/B pair.
5. **Vision source gate:** MiniCPM-V source download currently requires Hugging Face approval. Use only after access is granted; existing Ollama Q4 can still be recorded as Q4-only, not as an FP4 comparison.

## Test Cases and Scoring

- **Preprocessing:** fixed source snippets with expected symbol names, signatures and JSON schema. Score field validity and exact expected symbol coverage.
- **Fast/heavy code:** small bounded coding and multi-file editing tasks with hidden deterministic tests. Score test-pass rate and regression count.
- **Reasoning:** seeded bug reports with a known root cause and expected evidence. Score cause, supporting evidence and proposed fix against a fixed checklist.
- **General:** instruction-following and factual prompts with exact constraints and answer checklist. Score constraint compliance and factual correctness.
- **Vision:** fixed synthetic images for object/count, text, chart and spatial-relation questions. Score exact answer fields and per-question correctness.
- Use at least 8 cases per role set where available; report the denominator and each failure. Run each generation with `temperature=0`, `seed=42`, fixed context and output limits. Repeat performance measurement 3 times; report median time-to-first-token and tokens/second.
- Record peak VRAM and whether another model was evicted/reloaded. Keep concurrency at 1 for the controlled baseline.

## Execution Order

1. Re-read the active profile routes and record exact installed IDs, model digests, source revisions and quantization metadata.
2. Finish only already-authorized, feasible source downloads. Do not begin GPU work while the user is using it. MiniCPM gated access remains an external prerequisite.
3. When the user frees the GPU, verify no competing model runner and adequate VRAM. Test one small text model first to validate Transformers NVFP4 kernels, BitsAndBytes baseline, prompt parity and output capture.
4. Run unique supported text pairs from smallest to largest; unload each variant before loading its pair. Run Ollama 9B pair separately with explicit identical API options.
5. Run vision pairs only after confirming both model processors accept identical image inputs and fit on the GPU.
6. Record unsupported loads and hard limits without repeated retries. The 32B route is expected to be outside this host's 16 GB single-GPU capacity; verify by hardware accounting and mark untested if loading would exceed capacity.
7. Write measured results to `docs/agent-evaluation/fp4-q4-all-tier-evaluation-2026-11-23.md`; update the static support catalog only for exact, measured, quality-qualified entries.

## Acceptance

- Every distinct configured model-role pair appears as tested, blocked with evidence, or unsupported with a concrete reason.
- Every feasible model-role pair compares exact configured Q4 against same-source NVFP4; any format or runtime difference is explicit.
- Exact Qwen3.5 9B Ollama NVFP4/Q4_K_M pair uses identical prompt and API settings.
- Vision results use identical image bytes and visible per-case scoring.
- Report shows model/version digests, outputs or output artifact references, checks, timings and VRAM; all format/backend differences remain explicit.
- Catalog changes, if any, are limited to cases with measured runtime compatibility and passed quality checks.
