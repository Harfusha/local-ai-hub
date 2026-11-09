# Cross-vendor Embedding Acceleration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically route embedding and cross-encoder reranker work through the best available accelerator in the order NPU > dedicated GPU > integrated GPU > CPU, with vendor-specific support and safe fallback.

**Architecture:** Extend the existing embedding, reranker, and accelerator discovery paths rather than the generation-only background worker. Add vendor adapters behind optional dependencies, pin routes per indexing/ranking job, and preserve foreground priority and route-specific cache/index identity.

**Tech Stack:** Python 3.11+, Sentence Transformers/PyTorch, OpenVINO, Windows ML/ONNX Runtime execution providers, current Local AI Hub scheduler and state cache.

**Spec:** `docs/superpowers/specs/2026-11-09-cross-vendor-embedding-acceleration-design.md`

## Global Constraints

- Target Windows 11 first; support remains conditional on exact device, driver, runtime, OS build, and model operators.
- Priority order is NPU > dedicated GPU > integrated GPU > CPU.
- Keep model downloads, driver installs, runtime installs, and optional dependency installs opt-in.
- Build ONNX artifacts only from already cached model files; persist under configured `state_dir` and report progress.
- Foreground inference always wins; background embedding work yields at bounded batch boundaries.
- Preserve existing dirty worktree changes; review overlapping edits before changing the same paths.
- Tests and test commands are excluded until the user explicitly requests verification.

## Review Focus

- An unsupported or missing backend reports the actual reason and uses CPU only under the approved fallback policy.
- Explicit device selection never silently routes to another accelerator.
- Multiple adapters of one vendor resolve deterministically and expose the chosen device.
- A route failure cannot mix partial vectors from different route/precision identities.
- NPU and integrated GPU admission respects system-memory limits and foreground work.

---

### Task 1: Automatic device discovery and route policy

**Files:**
- Modify: `src/local_ai_hub/accelerators.py`
- Modify: `src/local_ai_hub/embeddings.py`
- Modify: `src/local_ai_hub/reranker.py`
- Modify: `src/local_ai_hub/hardware.py`
- Modify: `defaults.toml`
- Modify: `src/local_ai_hub/defaults.toml`
- Modify: relevant config validation and diagnostics modules identified during implementation

**Interfaces:**
- Consumes: installed runtime probes, detected adapter vendor/type, operator configuration.
- Produces: one stable route plan with ordered candidates: NPU, dedicated GPU, integrated GPU, CPU.

- [ ] Inspect the current worktree changes in all affected paths and identify ownership before editing.
- [ ] Add `auto` selection for embeddings and reranking with explicit per-vendor/device overrides and strict explicit selection.
- [ ] Preserve CPU fallback for `auto`; require explicit configuration to fallback from a failed explicit route.
- [ ] Report detected candidates, chosen route, and rejection/fallback reason.
- [ ] Review the diff for unchanged model defaults, config aliases, and user-local settings.

### Task 2: Vendor-specific embedding adapters

**Files:**
- Modify: `src/local_ai_hub/embeddings.py`
- Modify or create: focused provider adapter module(s) under `src/local_ai_hub/`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: stable route plan from Task 1 and the configured embedding model.
- Produces: CUDA for NVIDIA; OpenVINO for Intel GPU/NPU; ROCm for supported AMD GPU/APU; Windows ML/DirectML for AMD GPU fallback; Vitis AI through Windows ML for supported AMD Ryzen AI NPU.

- [ ] Reuse existing CUDA and OpenVINO implementations where their configured paths already work.
- [ ] Add optional provider dependencies without changing the default install footprint.
- [ ] Support local-only ONNX export/cache when an execution provider requires ONNX; expose progress and fail without downloading missing weights.
- [ ] Detect unsupported models/devices before committing embeddings and return a bounded diagnostic.
- [ ] Review adapter cleanup, timeout, model-load, and optional-import failure paths.

### Task 3: Scheduling, fallback, and index identity

**Files:**
- Modify: `src/local_ai_hub/embeddings.py`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/preprocess.py`
- Modify: current accelerator reservation/scheduler integration only where required

**Interfaces:**
- Consumes: pinned route for one indexing job and the existing foreground priority/reservation controls.
- Produces: homogeneous complete embeddings for each route identity; foreground requests can reclaim resources.

- [ ] Pin provider/device/precision for each indexing job and query/index pair.
- [ ] Yield after bounded batches; stop before mixing vectors if a route fails.
- [ ] Retain the last complete index until a replacement route finishes; restart the job on CPU only when fallback policy allows it.
- [ ] Keep caches and index metadata isolated by model, route, and precision when output parity is not established.
- [ ] Review cancellation, stale reservation, VRAM/RAM pressure, and partial-index recovery paths.

### Task 4: Operator configuration and documentation

**Files:**
- Modify: `docs/CONFIGURATION.md`
- Modify: `docs/INSTALLATION.md`
- Modify: `docs/INSTALL_PROMPT.md`
- Modify: `docs/UPDATE_PROMPT.md`
- Modify: relevant diagnostics/dashboard documentation

- [ ] Document the priority order, provider-specific runtime requirements, supported-device limits, optional install steps, fallback behavior, and reindex impact.
- [ ] Keep INSTALL and UPDATE prompts aligned with any new config flags or default routing.
- [ ] Review all documentation against the final provider and config surface.

## Verification Boundary

No automated tests, test files, or validation commands are included until the user explicitly requests verification. Completion must remain labeled implemented-but-unverified until that request is made and evidence is collected.
