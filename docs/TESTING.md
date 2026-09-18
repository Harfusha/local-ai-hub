# Testing and release gate

Run `python tools/release_check.py` first on the clean checkout, then `python -m compileall -q src tools tests`, `python -m pytest -q`, and `python tools/selftest.py`. The release check rejects local config, runtime databases, generated/cache payloads and internal workspaces before packaging. Pytest is configured to fail on resource leaks, unraisable exceptions and unhandled thread exceptions. Dashboard JavaScript is extracted and checked with Node when Node is available.

Focused release coverage includes `tests/test_release_contract.py`, `tests/test_release_runtime.py`, `tests/test_async_coordination_reliability.py`, and `tests/test_agent_state_reliability.py`. It checks guarded context documentation and schema, deterministic evidence precedence, concise machine-readable degradation warnings, missing preload/code-intelligence/local-model fallbacks, disabled Agent OS behavior, unchanged delta reuse, and legacy fast/full callers.

For every degraded response, assert both: (1) a bounded warning object with a stable `code` and actionable `message`; and (2) useful deterministic/indexed content, evidence, or continuation metadata. A timeout or unavailable optional backend is not permission to invent facts. Run the focused gate with:

```powershell
python -m pytest -q tests/test_release_contract.py tests/test_release_runtime.py tests/test_async_coordination_reliability.py tests/test_agent_state_reliability.py
```

Regression tests cover configuration/hardware profiles, setup behavior, repository filtering, external MCP transport/session lifecycle, preprocessing controls, deterministic/security/import analysis, code-index queries, cache recovery/LRU, semantic-cache vector decoding, command policy, bundles including binary embeddings/integrity/path limits, dashboard DOM/JS and a real HTTP subprocess with authentication/body limits/security headers/binary bundle upload.

CI runs CPython 3.11–3.14 on Windows, macOS and Linux. A release is packaged only after tests and self-test pass from a clean export; the final ZIP should then be extracted and tested again. Physical GPU/driver permutations cannot be executed in one CI host, so hardware detection/profile behavior is simulated in deterministic tests and platform matrix jobs.
