# llama.cpp Provider Selection and Managed Setup

## Problem

The repository exposes llama.cpp routing but treats the server as an unmanaged external dependency. Setup provisions only Ollama, while one doctor path reports missing Ollama as a failure even when Ollama is intentionally disabled. The install and operations documentation also says llama.cpp is never installed or started automatically. These mismatched policies let a valid llama.cpp configuration install successfully yet leave inference unavailable and diagnostics misleading.

## Design

Use one explicit provider decision throughout setup, runtime, service supervision, and diagnostics:

- If Ollama is enabled, use Ollama and do not install or start llama.cpp.
- If Ollama is disabled and `llama_cpp.mode = "on"`, llama.cpp is the selected backend. Setup provisions the pinned llama.cpp runtime and configured default model under `state`, and the Hub manages its loopback server lifecycle.
- `llama_cpp.mode = "auto"` continues to mean detect/use an already-running configured llama.cpp endpoint; it does not trigger downloads. `off` disables llama.cpp. No implicit provider switching occurs.
- When managed llama.cpp is selected, a failed SYCL/GPU startup retries on CPU. This is an execution fallback within llama.cpp, not a provider switch.
- Doctor, status, setup, and operator documentation report the selected provider and its actual health. An intentionally disabled backend is not a failure.

Downloads are version-pinned, bounded, checksum-verified, and stored only under the configured state directory. Unsupported platforms or failed verification produce an actionable setup error without silently selecting another provider. Existing external-server routing remains available in `auto` mode.

## Acceptance Criteria

1. A single provider-selection rule is shared by setup, runtime lifecycle, and diagnostics; Ollama-enabled installs never provision llama.cpp.
2. Explicit managed llama.cpp selection installs the pinned runtime and default model once, starts and restarts the local server with the Hub, and remains independent of Ollama.
3. GPU initialization failure retries on CPU and health checks identify the fallback mode.
4. Doctor and status pass or fail the selected provider accurately, and disabled providers are reported as disabled rather than failed.
5. Automated regression coverage exercises Ollama selection, managed llama.cpp selection, external `auto` mode, missing/unsupported runtime, failed download verification, CPU fallback, and doctor/status output.
6. README, operations/setup documentation, and both canonical install/update prompts describe the same selection and lifecycle rules.

## Constraints

- Runtime binaries, model files, logs, and mutable state remain under `server.state_dir`.
- Preserve loopback-only server access and the existing model-routing interface.
- Do not silently download or change inference providers when llama.cpp is not explicitly selected.
- Do not create commits, tags, pushes, or pull requests as part of this work.
