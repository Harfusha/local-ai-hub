# Model Residency Optimization Design

## Goal

Reduce foreground tail latency without weakening explicit fast, heavy, or reasoning roles.

## Decision

- Keep 7B as fast coding tier and 9B as heavy/reasoning tier; do not change their user-tuned offload, context, or quantization settings.
- Reuse a different resident model only after two numeric measurements for both candidates show it is within a small configured latency margin.
- Persist only model name plus latency, load, throughput, and sample count under `server.state_dir`. Never persist prompts, source, output, secrets, or project paths.
- Atomically write at first sample, when calibration becomes ready, and at a bounded interval thereafter.

## Safety

An unavailable, corrupt, or unwritable tuning file behaves as a cold tuner. Cold routing preserves requested model roles. Explicit heavy/reasoning requests remain authoritative.

## Verification

Unit tests prove numeric profile restoration, corrupt-state rejection, cold-role preservation, and measured resident reuse. Manual benchmark supplies paired 7B/9B samples.
