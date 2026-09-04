# Testing and release gate

Run `python -m pytest -q`, `python tools/selftest.py`, and `python -m compileall -q src tools tests`. Pytest is configured to fail on resource leaks, unraisable exceptions and unhandled thread exceptions. Dashboard JavaScript is extracted and checked with Node when Node is available.

Regression tests cover configuration/hardware profiles, setup behavior, repository filtering, external MCP transport/session lifecycle, preprocessing controls, deterministic/security/import analysis, code-index queries, cache recovery/LRU, semantic-cache vector decoding, command policy, bundles including binary embeddings/integrity/path limits, dashboard DOM/JS and a real HTTP subprocess with authentication/body limits/security headers/binary bundle upload.

CI runs CPython 3.11–3.14 on Windows, macOS and Linux. A release is packaged only after tests and self-test pass from a clean export; the final ZIP should then be extracted and tested again. Physical GPU/driver permutations cannot be executed in one CI host, so hardware detection/profile behavior is simulated in deterministic tests and platform matrix jobs.
