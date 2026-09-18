# Testing and release gate

Run `python tools/release_check.py` first on the clean checkout, then `python -m compileall -q src tools tests`, `python -m pytest -q`, and `python tools/selftest.py`. The release check rejects local config, runtime databases, generated/cache payloads and internal workspaces before packaging. Pytest is configured to fail on resource leaks, unraisable exceptions and unhandled thread exceptions. Dashboard JavaScript is extracted and checked with Node when Node is available.

Regression tests cover configuration/hardware profiles, setup behavior, repository filtering, external MCP transport/session lifecycle, preprocessing controls, deterministic/security/import analysis, code-index queries, cache recovery/LRU, semantic-cache vector decoding, command policy, bundles including binary embeddings/integrity/path limits, dashboard DOM/JS and a real HTTP subprocess with authentication/body limits/security headers/binary bundle upload.

## Performance probes

Use the bounded probe for representative workloads. It reports wall-clock min/mean/P50/P95/P99/max and suppresses target stdout/stderr:

```powershell
python tools/performance_probe.py --stage preprocess --iterations 3 --warmup 1 -- python -m pytest -q tests/test_performance.py -k preprocessor
python tools/performance_probe.py --stage index --iterations 3 --warmup 1 -- python -m pytest -q tests/test_performance.py -k batch_indexes
python tools/performance_probe.py --stage rag --iterations 3 --warmup 1 -- python -m pytest -q tests/test_rag_fragment_cache.py
python tools/performance_probe.py --stage mcp --iterations 3 --warmup 1 -- python -m pytest -q tests/test_mcp_server.py
python tools/performance_probe.py --stage http --iterations 3 --warmup 1 -- python -m pytest -q tests/test_http_server.py
```

All optional extras can be installed with `pip install -e ".[local-nlp,intel-accelerators,token-economy,performance,profiling,dev]"`. Add `--profiler py-spy` or `--profiler scalene` to print the exact wrapper command and availability. Do not accept an optimization based only on repository complexity; require a representative end-to-end improvement of roughly 15–20%.

The isolated Cython candidate can be measured with `python tools/cython_experiment.py`. It validates the kernel against Python and reports speedup, but stays disabled in production until the full workflow improves materially.

CI runs CPython 3.11–3.14 on Windows, macOS and Linux. A release is packaged only after tests and self-test pass from a clean export; the final ZIP should then be extracted and tested again. Physical GPU/driver permutations cannot be executed in one CI host, so hardware detection/profile behavior is simulated in deterministic tests and platform matrix jobs.
