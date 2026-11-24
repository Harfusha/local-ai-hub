# Pre-checked FP4 model catalog

## Goal

Before installation, check official model metadata for FP4 variants across every model family and size used by every hardware tier. Save those results in the shipped repository catalog. Installation and runtime only read the saved catalog; neither probes models nor queries a registry. Never infer model-format support from GPU compute capability alone.

## Decisions

- Catalog every model family and size in `PROFILE_OVERRIDES`, including hardware-dependent max-tier routes, preprocessing, vision and subagent models. Preserve the tiers and roles that use each family.
- Record exact official tag, format, backend, source, check date, and whether the variant is route-eligible for a stated provider/platform/architecture. Distinguish published support from route eligibility.
- The official Ollama tag catalog lists `qwen3.5:9b-nvfp4` as MLX. Prior NVIDIA RTX 5070 Ti runtime measurements establish observed execution/performance, not portable backend compatibility or model quality. Do not route it until exact active-backend compatibility and model-specific quality are qualified. Qwen2.5-Coder, Qwen3-VL and MiniCPM-V have no NVFP4 tag on their checked official tag pages and retain Q4. CUDA `has_fp4` alone never switches a model.
- Save catalog as package data in `src/local_ai_hub/data/fp4_model_support.json`. Runtime selects only exact prechecked entries; no cache, network lookup, model pull or conversion.
- Installer reads catalog version and selected static routes for reporting. It performs no FP4 audit, registry request or cache write.
- Preserve model-pull opt-in. Checking model tags never pulls weights or quantizes source weights.

## Acceptance criteria

1. Static catalog covers every model family and size used by all tiers, including max-only 32B heavy-code branch and preprocessing/vision/subagent models.
2. Catalog records official-source evidence and differentiates exact published FP4 variant from platform/backend and quality-qualified route eligibility.
3. Runtime applies only exact prechecked entries on matching provider/platform/architecture; unsupported or unmatched models retain configured Q4 route.
4. Installer only reads and reports the catalog. No model/backend probing, registry requests or FP4 audit cache writes occur during setup.
5. Runtime uses static catalog without network discovery, model pulls or reconversion.
6. Missing or malformed catalog fails closed to configured model.
7. Existing user model overrides and model-pull opt-ins remain authoritative.

## Validation

Review the resulting diff and run `git diff --check`. Do not run tests or install models in this task.
