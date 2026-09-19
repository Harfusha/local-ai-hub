# Testing and release gate

Release gate order matches CI: start from a clean checkout, run `python tools/release_check.py`, install the development extra with `python -m pip install -e ".[dev]"`, then run `python -m compileall -q src tools tests`, `pyflakes src tools`, `pytest -q`, `python tools/selftest.py`, and `python tools/check_dashboard.py`. Next run `python tools/release_check.py --post-test`; reject tracked mutations, remove expected ignored test/install caches with `git clean -fdX`, and run `python tools/release_check.py` again before packaging. Build the wheel and source distribution, then install the wheel into a fresh environment and smoke-test its version. The release check rejects local config, runtime databases, generated/cache payloads and internal workspaces. Pytest is configured to fail on resource leaks, unraisable exceptions and unhandled thread exceptions. Dashboard JavaScript is extracted and checked with Node when Node is available.

For a live developer installation that intentionally contains managed runtime state, use `python tools/release_check.py --allow-installed`. This allows only the documented installation/runtime directories and generated payloads; the clean-checkout and CI commands above remain strict.

Focused release coverage includes `tests/test_release_contract.py`, `tests/test_release_runtime.py`, `tests/test_async_coordination_reliability.py`, and `tests/test_agent_state_reliability.py`. It checks guarded context documentation and schema, deterministic evidence precedence, concise machine-readable degradation warnings, missing preload/code-intelligence/local-model fallbacks, disabled Agent OS behavior, unchanged delta reuse, and legacy fast/full callers.

For every degraded response, assert both: (1) a bounded warning object with a stable `code` and actionable `message`, when that fallback emits a warning; and (2) useful deterministic/indexed content, evidence, or continuation metadata. Deterministic fast fallback is identified by `degraded`, `context_source`, and `continuation`; guarded local-model fallback is identified by `model_degraded` and `model_degraded_reason`. A timeout or unavailable optional backend is not permission to invent facts. Run the focused gate with:

```powershell
python -m pytest -q tests/test_release_contract.py tests/test_release_runtime.py tests/test_async_coordination_reliability.py tests/test_agent_state_reliability.py
```

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

## Frontend vision review

The offline end-to-end contract is covered by `tests/test_frontend_review_e2e.py` and the deterministic page in `tests/fixtures/frontend_review/`. Run it without a browser, Ollama, network, credentials, or GPU:

```powershell
python -m pytest -q tests/test_frontend_review_e2e.py
```

The test feeds a mocked screenshot/evidence bundle through the public frontend-review context builders, maps findings to stable DOM IDs, keeps only relevant bounded coder context, repairs a temporary copy of the fixture, then rechecks the repaired state. The fixture intentionally contains a below-fold mobile CTA, low contrast, an unlabeled icon button, one console error, and a fake authenticated marker with no credentials.

For a real local review, use the current-tab bridge only after explicit user capture. Qwen3-VL:4B is selected through the configured llama.cpp vision route; the screenshot remains useful without DOM, while DOM/a11y/styles/runtime data improves finding-to-code mapping.
