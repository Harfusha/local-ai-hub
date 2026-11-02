# Case 088: bounded installed-model benchmark

`inputs.json` is the fixed, non-sensitive three-case dataset. The tested chat receives its path and the catalog prompt. Record the exact dataset hash, model identity and installed-model inventory before inference; model downloads are not permitted.

The complete run has one shared 60-second deadline, including all three cases and any warm-up or repeated measurement. A client-side observation timeout alone is insufficient: if the producer may still execute, report `outcome_unknown`, preserve its identity and do not start another run. Record per-case start, end, outcome, output and available token/latency metrics from the actual producer.

Label a run cold or warm only with an authentic model-residency observation tied to the same model and time. If residency is unknown, report unknown; do not infer cold from being the first measured request, unload a shared model, or modify the diagnostics toggle. A synthetic backend can exercise transport or timeout handling, but is not a model-performance measurement.

The generic `benchmark` operation runs a fixed suite and does not accept these inputs or a deadline. `hardware_benchmark` currently accepts one prompt but rejects `timeout_seconds`; neither proves this fixture's three-case shared hard deadline. Do not simulate support, silently drop the limit, run three unbounded calls, or label an incomplete run PASS. Wait for a supported bounded producer and required diagnostics authorization before live testing.
