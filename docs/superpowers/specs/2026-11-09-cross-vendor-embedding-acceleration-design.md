# Cross-vendor embedding acceleration

## Intent

Reduce CPU load and indexing time by running Local AI Hub's code/RAG embedding
and cross-encoder reranker models on available supported accelerators. The
current embedding default selects CPU; the reranker defaults to Torch/CPU. The
preprocessing GPU worker handles generation and explicitly excludes retrieval.

## Goals

- Automatically use a compatible GPU or NPU for embedding work on Windows 11.
- Automatically use the same compatible accelerator priority for cross-encoder
  reranking.
- Support NVIDIA discrete GPUs, AMD discrete and integrated GPUs, Intel
  integrated and discrete GPUs, Intel NPUs, and AMD Ryzen AI NPUs through
  vendor-appropriate backends. Availability depends on the exact device,
  driver, runtime, OS build, and model operators.
- Keep CPU execution as a safe, visible fallback when acceleration is disabled,
  missing, unsupported, or fails at model load or inference.
- Let operators select `auto`, a backend, and/or a specific device explicitly.
- Reuse the existing embedding model and preserve its dimensions, normalization,
  and cache/index identity semantics across device changes.
- Coordinate accelerator work with foreground model use; background indexing
  must yield to interactive work and avoid unbounded VRAM/system-memory pressure.
- Report selected backend/device and fallback reason in diagnostics.

## Existing behavior

The current `EmbeddingModel` supports configured Sentence Transformers on CUDA
and OpenVINO targets, including Intel GPU/NPU paths and CPU fallback. The
`Reranker` supports Torch/CUDA and OpenVINO, but its default explicitly selects
CPU. Both have cooperative CPU priority gates and GPU reservation hooks. The
generation-only background GPU worker remains separate from retrieval.

## Proposed backend routing

| Device | Preferred backend | Fallback |
| --- | --- | --- |
| NVIDIA discrete GPU | PyTorch/Sentence Transformers CUDA | CPU; Windows ML DirectML only if verified compatible |
| AMD discrete GPU | ROCm where the exact device/OS/runtime is supported; otherwise Windows ML DirectML | CPU |
| AMD integrated GPU | Windows ML DirectML; ROCm only where the exact APU is supported | CPU |
| Intel integrated/discrete GPU | Existing OpenVINO GPU plugin | CPU |
| Intel NPU | Existing OpenVINO NPU plugin | CPU |
| AMD Ryzen AI NPU | Windows ML Vitis AI execution provider | CPU |

The router must probe installed runtimes and actual devices; hardware-profile
labels alone do not prove backend availability. Set the default selection to
`auto`: prefer a compatible installed accelerator and fall back to CPU with a
diagnostic. An explicit backend/device request is strict by default and fails
visibly if unavailable; a separate explicit fallback setting may permit CPU.
Do not silently install drivers, runtime packages, or download model weights.
When an ONNX-based provider needs an artifact, allow a one-time local export
from already cached model files, show progress, and cache the result under
`state_dir`; never fetch missing source weights or silently quantize for an
NPU. Optional backend dependencies remain separately installable.

## Scheduling and correctness

- Automatic selection follows the operator-approved priority: NPU, dedicated
  GPU, integrated GPU, then CPU. An explicit operator choice overrides this
  preference. `auto` falls back to CPU with a diagnostic; explicit choices fail
  visibly unless CPU fallback is explicitly enabled.
- All accelerator inference must use bounded batches and participate in Hub
  scheduling. Foreground inference wins; background preprocessing yields or
  stops at a bounded point. Do not let one backend's failure poison other routes.
- Pin the selected route for each indexing job. If it fails, stop that job
  before mixing vectors, retain the last complete index, then restart on CPU
  when fallback is enabled. Bind query embeddings and persistent cache entries
  to the index's model/route/precision identity; a route change requires a new
  complete index before the new route becomes active.
- Bind each reranking cache key and ranking request to its selected model,
  backend, and device; never reuse cached scores across provider routes.
- If accelerator fallback occurs, expose the reason; never report GPU use when
  execution actually fell back to CPU.

## Non-goals

- Changing LLM generation routing or installing/configuring the user's machine.
- Promising support for every GPU generation, driver, Windows build, or model.
- Cross-platform acceleration in this first implementation; Linux/macOS remain
  out of scope unless the implementation can retain the same acceptance without
  expanding dependencies or weakening fallback behavior.

## Acceptance criteria

1. Each listed device class has a documented compatible route and runtime check.
   A device is supported only when its vendor runtime reports it and the chosen
   model compiles/runs; this is conditional support, not a promise for every SKU.
2. `auto` for embeddings and reranking selects a compatible installed
   accelerator and records the exact selected device; unsupported or
   unavailable routes use CPU with a reason.
3. Explicit backend/device settings are validated and do not silently select a
   different accelerator.
4. Model output shape, normalization, and index/cache compatibility remain
   correct when switching CPU and accelerator routes.
5. Background embedding batches yield to foreground work and remain bounded.
6. Configuration, installation, troubleshooting, and diagnostics explain
   optional dependencies, supported hardware limits, and fallback behavior.

## Builder decisions

- Treat Windows 11 as the first target because the active installation is on
  Windows; keep backend boundaries open for later Linux support.
- Prefer a known vendor-native backend where available; use Windows ML/DirectML
  for broad AMD DX12 fallback because the project needs separate vendor/device
  routes and DirectML is in sustained engineering.
- Do not enable unconstrained concurrent embedding and foreground LLM loads.
- Do not change user-local runtime settings or install optional packages as part
  of feature activation.

## Current technical evidence

- Repository defaults use `sentence-transformers` and CPU for embeddings.
- The current background GPU worker is for generation and excludes CPU
  embeddings/reranking.
- OpenVINO documents Intel integrated/discrete GPU and NPU targets.
- ONNX Runtime documents DirectML for broad DirectX 12 GPU hardware, and marks
  DirectML as sustained engineering with Windows ML as the forward path.
- AMD documents ROCm support for selected Radeon and Ryzen GPU/APU families on
  specific Windows builds, and Vitis AI/Windows ML support for Ryzen AI NPU.
